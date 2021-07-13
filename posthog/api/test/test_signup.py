import datetime
import uuid
from typing import cast
from unittest.mock import patch

import pytest
import pytz
from django.core import mail
from django.utils import timezone
from rest_framework import status

from posthog.models import Dashboard, Organization, Team, User
from posthog.models.organization import OrganizationInvite
from posthog.test.base import APIBaseTest
from posthog.utils import get_instance_realm


class TestSignupAPI(APIBaseTest):
    @classmethod
    def setUpTestData(cls):
        # Do not set up any test data
        pass

    @pytest.mark.skip_on_multitenancy
    @patch("posthog.api.organization.settings.EE_AVAILABLE", False)
    @patch("posthoganalytics.capture")
    def test_api_sign_up(self, mock_capture):
        response = self.client.post(
            "/api/signup/",
            {
                "first_name": "John",
                "email": "hedgehog@posthog.com",
                "password": "notsecure",
                "organization_name": "Hedgehogs United, LLC",
                "email_opt_in": False,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = cast(User, User.objects.order_by("-pk")[0])
        team = cast(Team, user.team)
        organization = cast(Organization, user.organization)

        self.assertEqual(
            response.json(),
            {
                "id": user.pk,
                "uuid": str(user.uuid),
                "distinct_id": user.distinct_id,
                "first_name": "John",
                "email": "hedgehog@posthog.com",
                "redirect_url": "/ingestion",
            },
        )

        # Assert that the user was properly created
        self.assertEqual(user.first_name, "John")
        self.assertEqual(user.email, "hedgehog@posthog.com")
        self.assertEqual(user.email_opt_in, False)

        # Assert that the team was properly created
        self.assertEqual(team.name, "Default Project")

        # Assert that the org was properly created
        self.assertEqual(organization.name, "Hedgehogs United, LLC")

        # Assert that the sign up event & identify calls were sent to PostHog analytics
        mock_capture.assert_called_once_with(
            user.distinct_id,
            "user signed up",
            properties={
                "is_first_user": True,
                "is_organization_first_user": True,
                "new_onboarding_enabled": False,
                "signup_backend_processor": "OrganizationSignupSerializer",
                "signup_social_provider": "",
                "realm": get_instance_realm(),
            },
        )

        # Assert that the user is logged in
        response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], "hedgehog@posthog.com")

        # Assert that the password was correctly saved
        self.assertTrue(user.check_password("notsecure"))

    @pytest.mark.skip_on_multitenancy
    def test_signup_disallowed_on_self_hosted_by_default(self):
        with self.settings(MULTI_TENANCY=False):
            response = self.client.post(
                "/api/signup/", {"first_name": "Jane", "email": "hedgehog2@posthog.com", "password": "notsecure"},
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            response = self.client.post(
                "/api/signup/", {"first_name": "Jane", "email": "hedgehog2@posthog.com", "password": "notsecure"},
            )
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(
                response.json(),
                {
                    "attr": None,
                    "code": "permission_denied",
                    "detail": "New organizations cannot be created in this instance. Contact your administrator if you"
                    " think this is a mistake.",
                    "type": "authentication_error",
                },
            )

    @pytest.mark.ee
    def test_signup_allowed_on_self_hosted_with_env_var(self):
        from ee.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123", plan="enterprise", valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7), max_users=3,
        )

        Organization.objects.create(name="name")
        User.objects.create(first_name="name", email="email@posthog.com")
        count = Organization.objects.count()
        with self.settings(MULTI_TENANCY=False, MULTI_ORG_ENABLED=True):
            response = self.client.post(
                "/api/signup/", {"first_name": "Jane", "email": "hedgehog4@posthog.com", "password": "notsecure"},
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["email"], "hedgehog4@posthog.com")
        self.assertEqual(Organization.objects.count(), count + 1)

    @pytest.mark.skip_on_multitenancy
    @patch("posthoganalytics.capture")
    @patch("posthoganalytics.identify")
    def test_signup_minimum_attrs(self, mock_identify, mock_capture):
        response = self.client.post(
            "/api/signup/", {"first_name": "Jane", "email": "hedgehog2@posthog.com", "password": "notsecure"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user = cast(User, User.objects.order_by("-pk").get())
        organization = cast(Organization, user.organization)
        self.assertEqual(
            response.json(),
            {
                "id": user.pk,
                "uuid": str(user.uuid),
                "distinct_id": user.distinct_id,
                "first_name": "Jane",
                "email": "hedgehog2@posthog.com",
                "redirect_url": "/ingestion",
            },
        )

        # Assert that the user & org were properly created
        self.assertEqual(user.first_name, "Jane")
        self.assertEqual(user.email, "hedgehog2@posthog.com")
        self.assertEqual(user.email_opt_in, True)  # Defaults to True
        self.assertEqual(organization.name, "Jane")

        # Assert that the sign up event & identify calls were sent to PostHog analytics
        mock_identify.assert_called_once()
        mock_capture.assert_called_once_with(
            user.distinct_id,
            "user signed up",
            properties={
                "is_first_user": True,
                "is_organization_first_user": True,
                "new_onboarding_enabled": False,
                "signup_backend_processor": "OrganizationSignupSerializer",
                "signup_social_provider": "",
                "realm": get_instance_realm(),
            },
        )

        # Assert that the user is logged in
        response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], "hedgehog2@posthog.com")

        # Assert that the password was correctly saved
        self.assertTrue(user.check_password("notsecure"))

    def test_cant_sign_up_without_required_attributes(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()
        org_count: int = Organization.objects.count()

        required_attributes = [
            "first_name",
            "email",
            "password",
        ]

        for attribute in required_attributes:
            body = {
                "first_name": "Jane",
                "email": "invalid@posthog.com",
                "password": "notsecure",
            }
            body.pop(attribute)

            # Make sure the endpoint works with and without the trailing slash
            response = self.client.post("/api/signup", body)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "required",
                    "detail": "This field is required.",
                    "attr": attribute,
                },
            )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)
        self.assertEqual(Organization.objects.count(), org_count)

    def test_cant_sign_up_with_short_password(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()

        response = self.client.post(
            "/api/signup/", {"first_name": "Jane", "email": "failed@posthog.com", "password": "123"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "password_too_short",
                "detail": "This password is too short. It must contain at least 8 characters.",
                "attr": "password",
            },
        )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)

    @patch("posthoganalytics.feature_enabled")
    def test_default_dashboard_is_created_on_signup(self, mock_feature_enabled):
        """
        Tests that the default web app dashboard is created on signup.
        Note: This feature is currently behind a feature flag.
        """

        response = self.client.post(
            "/api/signup/",
            {
                "first_name": "Jane",
                "email": "hedgehog75@posthog.com",
                "password": "notsecure",
                "redirect_url": "/ingestion",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        user: User = User.objects.order_by("-pk").get()

        mock_feature_enabled.assert_any_call("new-onboarding-2822", user.distinct_id)

        self.assertEqual(
            response.json(),
            {
                "id": user.pk,
                "uuid": str(user.uuid),
                "distinct_id": user.distinct_id,
                "first_name": "Jane",
                "email": "hedgehog75@posthog.com",
                "redirect_url": "/personalization",
            },
        )

        dashboard: Dashboard = Dashboard.objects.first()  # type: ignore
        self.assertEqual(dashboard.team, user.team)
        self.assertEqual(dashboard.items.count(), 1)
        self.assertEqual(dashboard.name, "Web Analytics")
        self.assertEqual(
            dashboard.items.all()[0].description, "Shows a conversion funnel from sign up to watching a movie."
        )

        # Particularly assert that the default dashboards are not created (because we create special demo dashboards)
        self.assertEqual(Dashboard.objects.filter(team=user.team).count(), 3)  # Web, app & revenue demo dashboards


class TestInviteSignup(APIBaseTest):
    """
    Tests the sign up process for users with an invite (i.e. existing organization).
    """

    CONFIG_EMAIL = None

    # Invite pre-validation

    def test_api_invite_sign_up_prevalidate(self):
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+19@posthog.com", organization=self.organization,
        )

        response = self.client.get(f"/api/signup/{invite.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "id": str(invite.id),
                "target_email": "t*****9@posthog.com",
                "first_name": "",
                "organization_name": self.CONFIG_ORGANIZATION_NAME,
            },
        )

    def test_api_invite_sign_up_with_first_name_prevalidate(self):
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+58@posthog.com", organization=self.organization, first_name="Jane"
        )

        response = self.client.get(f"/api/signup/{invite.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "id": str(invite.id),
                "target_email": "t*****8@posthog.com",
                "first_name": "Jane",
                "organization_name": self.CONFIG_ORGANIZATION_NAME,
            },
        )

    def test_api_invite_sign_up_prevalidate_for_existing_user(self):
        user = self._create_user("test+29@posthog.com", "test_password")
        new_org = Organization.objects.create(name="Test, Inc")
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+29@posthog.com", organization=new_org,
        )

        self.client.force_login(user)
        response = self.client.get(f"/api/signup/{invite.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "id": str(invite.id),
                "target_email": "t*****9@posthog.com",
                "first_name": "",
                "organization_name": "Test, Inc",
            },
        )

    def test_api_invite_sign_up_prevalidate_invalid_invite(self):

        for invalid_invite in [uuid.uuid4(), "abc", "1234"]:
            response = self.client.get(f"/api/signup/{invalid_invite}/")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "invalid_input",
                    "detail": "The provided invite ID is not valid.",
                    "attr": None,
                },
            )

    def test_existing_user_cant_claim_invite_if_it_doesnt_match_target_email(self):
        user = self._create_user("test+39@posthog.com", "test_password")
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+49@posthog.com", organization=self.organization,
        )

        self.client.force_login(user)
        response = self.client.get(f"/api/signup/{invite.id}/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_recipient",
                "detail": "This invite is intended for another email address: t*****9@posthog.com."
                " You tried to sign up with test+39@posthog.com.",
                "attr": None,
            },
        )

    def test_api_invite_sign_up_prevalidate_expired_invite(self):
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+59@posthog.com", organization=self.organization,
        )
        invite.created_at = datetime.datetime(2020, 12, 1, tzinfo=pytz.UTC)
        invite.save()

        response = self.client.get(f"/api/signup/{invite.id}/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "expired",
                "detail": "This invite has expired. Please ask your admin for a new one.",
                "attr": None,
            },
        )

    # Signup (using invite)

    @patch("posthoganalytics.capture")
    @patch("posthog.api.organization.settings.EE_AVAILABLE", True)
    def test_api_invite_sign_up(self, mock_capture):
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+99@posthog.com", organization=self.organization,
        )

        response = self.client.post(
            f"/api/signup/{invite.id}/", {"first_name": "Alice", "password": "test_password", "email_opt_in": True},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = cast(User, User.objects.order_by("-pk")[0])
        self.assertEqual(
            response.json(),
            {
                "id": user.pk,
                "uuid": str(user.uuid),
                "distinct_id": user.distinct_id,
                "first_name": "Alice",
                "email": "test+99@posthog.com",
            },
        )

        # User is now a member of the organization
        self.assertEqual(user.organization_memberships.count(), 1)
        self.assertEqual(user.organization_memberships.first().organization, self.organization)  # type: ignore

        # Defaults are set correctly
        self.assertEqual(user.organization, self.organization)
        self.assertEqual(user.team, self.team)

        # Assert that the user was properly created
        self.assertEqual(user.first_name, "Alice")
        self.assertEqual(user.email, "test+99@posthog.com")
        self.assertEqual(user.email_opt_in, True)

        # Assert that the sign up event & identify calls were sent to PostHog analytics
        mock_capture.assert_called_once_with(
            user.distinct_id,
            "user signed up",
            properties={
                "is_first_user": False,
                "is_organization_first_user": False,
                "new_onboarding_enabled": False,
                "signup_backend_processor": "OrganizationInviteSignupSerializer",
                "signup_social_provider": "",
                "realm": get_instance_realm(),
            },
        )

        # Assert that the user is logged in
        response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["email"], "test+99@posthog.com")

        # Assert that the password was correctly saved
        self.assertTrue(user.check_password("test_password"))

    @patch("posthog.api.organization.settings.EE_AVAILABLE", False)
    def test_api_invite_sign_up_member_joined_email_is_not_sent_for_initial_member(self):
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+100@posthog.com", organization=self.organization,
        )

        with self.settings(EMAIL_ENABLED=True, EMAIL_HOST="localhost", SITE_URL="http://test.posthog.com"):
            response = self.client.post(
                f"/api/signup/{invite.id}/", {"first_name": "Alice", "password": "test_password", "email_opt_in": True},
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(len(mail.outbox), 0)

    @patch("posthog.api.organization.settings.EE_AVAILABLE", False)
    def test_api_invite_sign_up_member_joined_email_is_sent_for_next_members(self):
        initial_user = User.objects.create_and_join(self.organization, "test+420@posthog.com", None)

        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+100@posthog.com", organization=self.organization,
        )

        with self.settings(EMAIL_ENABLED=True, EMAIL_HOST="localhost", SITE_URL="http://test.posthog.com"):
            response = self.client.post(
                f"/api/signup/{invite.id}/", {"first_name": "Alice", "password": "test_password", "email_opt_in": True},
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(len(mail.outbox), 1)
        self.assertListEqual(mail.outbox[0].to, [initial_user.email])

    @patch("posthoganalytics.identify")
    @patch("posthoganalytics.capture")
    @patch("posthog.api.organization.settings.EE_AVAILABLE", False)
    def test_existing_user_can_sign_up_to_a_new_organization(self, mock_capture, mock_identify):
        user = self._create_user("test+159@posthog.com", "test_password")
        new_org = Organization.objects.create(name="TestCo")
        new_team = Team.objects.create(organization=new_org)
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+159@posthog.com", organization=new_org,
        )

        self.client.force_login(user)

        count = User.objects.count()

        with self.settings(MULTI_TENANCY=True):
            response = self.client.post(f"/api/signup/{invite.id}/")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.json(),
            {
                "id": user.pk,
                "uuid": str(user.uuid),
                "distinct_id": user.distinct_id,
                "first_name": "",
                "email": "test+159@posthog.com",
            },
        )

        # No new user is created
        self.assertEqual(User.objects.count(), count)

        # User is now a member of the organization
        user.refresh_from_db()
        self.assertEqual(user.organization_memberships.count(), 2)
        self.assertTrue(user.organization_memberships.filter(organization=new_org).exists())

        # User is now changed to the new organization
        self.assertEqual(user.organization, new_org)
        self.assertEqual(user.team, new_team)

        # User is not changed
        self.assertEqual(user.first_name, "")
        self.assertEqual(user.email, "test+159@posthog.com")

        # Assert that the sign up event & identify calls were sent to PostHog analytics
        mock_capture.assert_called_once_with(
            user.distinct_id,
            "user joined organization",
            properties={
                "organization_id": str(new_org.id),
                "user_number_of_org_membership": 2,
                "org_current_invite_count": 0,
                "org_current_project_count": 1,
                "org_current_members_count": 1,
            },
        )
        mock_identify.assert_called_once()

        # Assert that the user remains logged in
        response = self.client.get("/api/user/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @patch("posthoganalytics.capture")
    def test_cannot_use_claim_invite_endpoint_to_update_user(self, mock_capture):
        """
        Tests that a user cannot use the claim invite endpoint to change their name or password
        (as this endpoint does not do any checks that might be required).
        """
        new_org = Organization.objects.create(name="TestCo")
        user = self._create_user("test+189@posthog.com", "test_password")
        user2 = self._create_user("test+949@posthog.com")
        user2.join(organization=new_org)

        Team.objects.create(organization=new_org)
        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+189@posthog.com", organization=new_org,
        )

        self.client.force_login(user)

        response = self.client.post(f"/api/signup/{invite.id}/", {"first_name": "Bob", "password": "new_password"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.json(),
            {
                "id": user.pk,
                "uuid": str(user.uuid),
                "distinct_id": user.distinct_id,
                "first_name": "",
                "email": "test+189@posthog.com",
            },  # note the unchanged attributes
        )

        # User is subscribed to the new organization
        user.refresh_from_db()
        self.assertTrue(user.organization_memberships.filter(organization=new_org).exists())

        # User is not changed
        self.assertEqual(user.first_name, "")
        self.assertFalse(user.check_password("new_password"))  # Password is not updated

        # Assert that the sign up event & identify calls were sent to PostHog analytics
        mock_capture.assert_called_once_with(
            user.distinct_id,
            "user joined organization",
            properties={
                "organization_id": str(new_org.id),
                "user_number_of_org_membership": 2,
                "org_current_invite_count": 0,
                "org_current_project_count": 1,
                "org_current_members_count": 2,
            },
        )

    def test_cant_claim_sign_up_invite_without_required_attributes(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()
        org_count: int = Organization.objects.count()

        required_attributes = [
            "first_name",
            "password",
        ]

        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+799@posthog.com", organization=self.organization,
        )

        for attribute in required_attributes:
            body = {
                "first_name": "Charlie",
                "password": "test_password",
            }
            body.pop(attribute)

            response = self.client.post(f"/api/signup/{invite.id}/", body)
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "required",
                    "detail": "This field is required.",
                    "attr": attribute,
                },
            )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)
        self.assertEqual(Organization.objects.count(), org_count)

    def test_cant_claim_invite_sign_up_with_short_password(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()
        org_count: int = Organization.objects.count()

        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+799@posthog.com", organization=self.organization,
        )

        response = self.client.post(f"/api/signup/{invite.id}/", {"first_name": "Charlie", "password": "123"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "password_too_short",
                "detail": "This password is too short. It must contain at least 8 characters.",
                "attr": "password",
            },
        )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)
        self.assertEqual(Organization.objects.count(), org_count)

    def test_cant_claim_invalid_invite(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()
        org_count: int = Organization.objects.count()

        response = self.client.post(
            f"/api/signup/{uuid.uuid4()}/", {"first_name": "Charlie", "password": "test_password"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "The provided invite ID is not valid.",
                "attr": None,
            },
        )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)
        self.assertEqual(Organization.objects.count(), org_count)

    def test_cant_claim_expired_invite(self):
        count: int = User.objects.count()
        team_count: int = Team.objects.count()
        org_count: int = Organization.objects.count()

        invite: OrganizationInvite = OrganizationInvite.objects.create(
            target_email="test+799@posthog.com", organization=self.organization,
        )
        invite.created_at = datetime.datetime(2020, 3, 3, tzinfo=pytz.UTC)
        invite.save()

        response = self.client.post(f"/api/signup/{invite.id}/", {"first_name": "Charlie", "password": "test_password"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "expired",
                "detail": "This invite has expired. Please ask your admin for a new one.",
                "attr": None,
            },
        )

        self.assertEqual(User.objects.count(), count)
        self.assertEqual(Team.objects.count(), team_count)
        self.assertEqual(Organization.objects.count(), org_count)

    # Social signup (use invite)

    def test_api_social_invite_sign_up(self):
        Organization.objects.all().delete()  # Can only create organizations in fresh instances

        # simulate SSO process started
        session = self.client.session
        session.update({"backend": "google-oauth2"})
        session.save()

        response = self.client.post("/api/social_signup", {"organization_name": "Tech R Us", "email_opt_in": False})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(response.json(), {"continue_url": "/complete/google-oauth2/"})

        # Check the values were saved in the session
        self.assertEqual(self.client.session.get("organization_name"), "Tech R Us")
        self.assertEqual(self.client.session.get("email_opt_in"), False)
        self.assertEqual(self.client.session.get_expiry_age(), 3600)

    def test_cannot_use_social_invite_sign_up_if_social_session_is_not_active(self):
        Organization.objects.all().delete()  # Can only create organizations in fresh instances

        response = self.client.post("/api/social_signup", {"organization_name": "Tech R Us", "email_opt_in": False})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Inactive social login session. Go to /login and log in before continuing.",
                "attr": None,
            },
        )
        self.assertEqual(len(self.client.session.keys()), 0)  # Nothing is saved in the session

    def test_cannot_use_social_invite_sign_up_without_required_attributes(self):
        Organization.objects.all().delete()  # Can only create organizations in fresh instances

        response = self.client.post("/api/social_signup", {"email_opt_in": False})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "required",
                "detail": "This field is required.",
                "attr": "organization_name",
            },
        )
        self.assertEqual(len(self.client.session.keys()), 0)  # Nothing is saved in the session
