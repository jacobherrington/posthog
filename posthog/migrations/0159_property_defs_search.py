# Generated by Django 3.1.12 on 2021-07-08 12:40

from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0158_new_token_format"),
    ]

    operations = [TrigramExtension()]