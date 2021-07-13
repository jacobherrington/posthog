import React, { ForwardRefRenderFunction, useEffect, useRef, useState } from 'react'
import { humanFriendlyDuration, humanizeNumber } from 'lib/utils'
import { FunnelStep } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Button, ButtonProps, Popover } from 'antd'
import { ArrowRightOutlined } from '@ant-design/icons'
import { useResizeObserver } from 'lib/utils/responsiveUtils'
import { SeriesGlyph } from 'lib/components/SeriesGlyph'
import { ArrowBottomRightOutlined } from 'lib/components/icons'
import { funnelLogic } from './funnelLogic'
import { useThrottledCallback } from 'use-debounce'
import './FunnelBarGraph.scss'
import { useActions, useValues } from 'kea'
import { FunnelBarLayout } from 'lib/constants'
import { FunnelStepReference } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepReferencePicker'
import { InsightTooltip } from 'scenes/insights/InsightTooltip'

import {
    calcPercentage,
    getReferenceStep,
    humanizeOrder,
    getSeriesColor,
    getBreakdownMaxIndex,
    getSeriesPositionName,
} from './funnelUtils'

interface FunnelBarGraphProps {
    layout?: FunnelBarLayout
    steps: FunnelStep[]
}

interface BarProps {
    percentage: number
    name?: string
    onBarClick?: () => void
    layout?: FunnelBarLayout
    isBreakdown?: boolean
    breakdownIndex?: number
    breakdownMaxIndex?: number
    breakdownSumPercentage?: number
    popoverTitle?: string | JSX.Element | null
    popoverMetrics?: { title: string; value: number | string; visible?: boolean }[]
}

type LabelPosition = 'inside' | 'outside'

function Bar({
    percentage,
    name,
    onBarClick,
    layout = FunnelBarLayout.horizontal,
    isBreakdown = false,
    breakdownIndex,
    breakdownMaxIndex,
    breakdownSumPercentage,
    popoverTitle = null,
    popoverMetrics = [],
}: BarProps): JSX.Element {
    const barRef = useRef<HTMLDivElement | null>(null)
    const labelRef = useRef<HTMLDivElement | null>(null)
    const [labelPosition, setLabelPosition] = useState<LabelPosition>('inside')
    const [labelVisible, setLabelVisible] = useState(true)
    const LABEL_POSITION_OFFSET = 8 // Defined here and in SCSS
    const { funnelPersonsEnabled } = useValues(funnelLogic)
    const dimensionProperty = layout === FunnelBarLayout.horizontal ? 'width' : 'height'
    const cursorType = funnelPersonsEnabled ? 'pointer' : ''
    const hasBreakdownSum = isBreakdown && typeof breakdownSumPercentage === 'number'
    const shouldShowLabel = !isBreakdown || (hasBreakdownSum && labelVisible)

    function decideLabelPosition(): void {
        if (hasBreakdownSum) {
            // Label is always outside for breakdowns, but don't show if it doesn't fit in the wrapper
            setLabelPosition('outside')
            if (layout === FunnelBarLayout.horizontal) {
                const barWidth = barRef.current?.clientWidth ?? null
                const barOffset = barRef.current?.offsetLeft ?? null
                const wrapperWidth = barRef.current?.parentElement?.clientWidth ?? null
                const labelWidth = labelRef.current?.clientWidth ?? null
                if (barWidth !== null && barOffset !== null && wrapperWidth !== null && labelWidth !== null) {
                    if (wrapperWidth - (barWidth + barOffset) < labelWidth + LABEL_POSITION_OFFSET * 2) {
                        setLabelVisible(false)
                    } else {
                        setLabelVisible(true)
                    }
                }
            } else {
                const barOffset = barRef.current?.offsetTop ?? null
                const labelHeight = labelRef.current?.clientHeight ?? null
                if (barOffset !== null && labelHeight !== null) {
                    if (barOffset < labelHeight + LABEL_POSITION_OFFSET * 2) {
                        setLabelVisible(false)
                    } else {
                        setLabelVisible(true)
                    }
                }
            }
            return
        }
        // Place label inside or outside bar, based on whether it fits
        if (layout === FunnelBarLayout.horizontal) {
            const barWidth = barRef.current?.clientWidth ?? null
            const labelWidth = labelRef.current?.clientWidth ?? null
            if (barWidth !== null && labelWidth !== null) {
                if (labelWidth + LABEL_POSITION_OFFSET * 2 > barWidth) {
                    setLabelPosition('outside')
                    return
                }
            }
        } else {
            const barHeight = barRef.current?.clientHeight ?? null
            const labelHeight = labelRef.current?.clientHeight ?? null
            if (barHeight !== null && labelHeight !== null) {
                if (labelHeight + LABEL_POSITION_OFFSET * 2 > barHeight) {
                    setLabelPosition('outside')
                    return
                }
            }
        }
        setLabelPosition('inside')
    }

    useResizeObserver({
        callback: useThrottledCallback(decideLabelPosition, 200),
        element: barRef,
    })

    return (
        <Popover
            trigger="hover"
            placement="right"
            content={
                <InsightTooltip chartType="funnel" altTitle={popoverTitle}>
                    {popoverMetrics.map(({ title, value, visible }, index) =>
                        visible !== false ? <MetricRow key={index} title={title} value={value} /> : null
                    )}
                </InsightTooltip>
            }
        >
            <div
                ref={barRef}
                className={`funnel-bar ${getSeriesPositionName(breakdownIndex, breakdownMaxIndex)}`}
                style={{
                    [dimensionProperty]: `${percentage}%`,
                    cursor: cursorType,
                    backgroundColor: getSeriesColor(breakdownIndex),
                }}
                onClick={() => {
                    if (funnelPersonsEnabled && onBarClick) {
                        onBarClick()
                    }
                }}
            >
                {shouldShowLabel && (
                    <div
                        ref={labelRef}
                        className={`funnel-bar-percentage ${labelPosition}`}
                        title={name ? `Users who did ${name}` : undefined}
                        role="progressbar"
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={breakdownSumPercentage ?? percentage}
                    >
                        {humanizeNumber(breakdownSumPercentage ?? percentage, 2)}%
                    </div>
                )}
            </div>
        </Popover>
    )
}

interface ValueInspectorButtonProps {
    icon?: JSX.Element
    onClick: (e?: React.MouseEvent) => void
    children: React.ReactNode
    disabled?: boolean
    style?: React.CSSProperties
    title?: string | undefined
    innerRef?: React.MutableRefObject<HTMLElement | null>
}

function ValueInspectorButton({
    icon,
    onClick,
    children,
    disabled = false,
    style,
    title,
    innerRef: refProp,
}: ValueInspectorButtonProps): JSX.Element {
    const props = {
        type: 'link' as const,
        icon,
        onClick,
        className: 'funnel-inspect-button',
        disabled,
        style,
        title,
        children: <span className="funnel-inspect-label">{children}</span>,
    }
    if (refProp) {
        const InnerComponent: ForwardRefRenderFunction<HTMLElement | null, ButtonProps> = (_, ref) => (
            <Button ref={ref} {...props} />
        )
        const RefComponent = React.forwardRef(InnerComponent)
        return <RefComponent ref={refProp} />
    } else {
        return <Button {...props} />
    }
}

interface AverageTimeInspectorProps {
    onClick: (e?: React.MouseEvent) => void
    disabled?: boolean
    averageTime: number
}

function AverageTimeInspector({ onClick, disabled, averageTime }: AverageTimeInspectorProps): JSX.Element {
    // Inspector button which automatically shows/hides the info text.
    const wrapperRef = useRef<HTMLDivElement | null>(null)
    const infoTextRef = useRef<HTMLDivElement | null>(null)
    const buttonRef = useRef<HTMLDivElement | null>(null)
    const [infoTextVisible, setInfoTextVisible] = useState(true)

    function decideTextVisible(): void {
        // Show/hide label position based on whether both items fit horizontally
        const wrapperWidth = wrapperRef.current?.clientWidth ?? null
        const infoTextWidth = infoTextRef.current?.offsetWidth ?? null
        const buttonWidth = buttonRef.current?.offsetWidth ?? null

        if (wrapperWidth !== null && infoTextWidth !== null && buttonWidth !== null) {
            if (infoTextWidth + buttonWidth <= wrapperWidth) {
                setInfoTextVisible(true)
                return
            }
        }
        setInfoTextVisible(false)
    }

    useEffect(() => {
        decideTextVisible()
    }, [])

    useResizeObserver({
        callback: useThrottledCallback(decideTextVisible, 200),
        element: wrapperRef,
    })

    return (
        <div ref={wrapperRef}>
            <span
                ref={infoTextRef}
                className="text-muted"
                style={{ paddingRight: 4, display: 'inline-block', visibility: infoTextVisible ? undefined : 'hidden' }}
            >
                Average time:
            </span>
            <ValueInspectorButton
                innerRef={buttonRef}
                style={{ paddingLeft: 0, paddingRight: 0 }}
                onClick={onClick}
                disabled={disabled}
                title="Average time elapsed between completing this step and starting the next one."
            >
                {humanFriendlyDuration(averageTime, 2)}
            </ValueInspectorButton>
        </div>
    )
}

function MetricRow({ title, value }: { title: string; value: string | number }): JSX.Element {
    return (
        <div style={{ width: '100%', display: 'flex', justifyContent: 'space-between' }}>
            <div>{title}</div>
            <div>
                <strong>{value}</strong>
            </div>
        </div>
    )
}

export function FunnelBarGraph({ steps: stepsParam }: FunnelBarGraphProps): JSX.Element {
    const { stepReference, barGraphLayout: layout, funnelPersonsEnabled } = useValues(funnelLogic)
    const { openPersonsModal } = useActions(funnelLogic)
    const steps = [...stepsParam].sort((a, b) => a.order - b.order)
    const firstStep = getReferenceStep(steps, FunnelStepReference.total)

    return (
        <div className={`funnel-bar-graph ${layout}`}>
            {steps.map((step, i) => {
                const basisStep = getReferenceStep(steps, stepReference, i)
                const previousStep = getReferenceStep(steps, FunnelStepReference.previous, i)
                const previousCount = previousStep?.count ?? 0
                const dropoffCount = previousCount - step.count
                const showLineBefore = layout === FunnelBarLayout.horizontal && i > 0
                const showLineAfter = layout === FunnelBarLayout.vertical || i < steps.length - 1
                const breakdownMaxIndex = getBreakdownMaxIndex(step.breakdown)
                const breakdownSum = step.breakdown?.reduce((sum, item) => sum + item.count, 0)
                return (
                    <section key={step.order} className="funnel-step">
                        <div className="funnel-series-container">
                            <div className={`funnel-series-linebox ${showLineBefore ? 'before' : ''}`} />
                            <SeriesGlyph style={{ backgroundColor: '#fff', zIndex: 2 }}>
                                {humanizeOrder(step.order)}
                            </SeriesGlyph>
                            <div className={`funnel-series-linebox ${showLineAfter ? 'after' : ''}`} />
                        </div>
                        <header>
                            <div className="funnel-step-title">
                                <PropertyKeyInfo value={step.name} />
                            </div>
                            <div className={`funnel-step-metadata ${layout}`}>
                                {step.average_conversion_time && step.average_conversion_time >= 0 + Number.EPSILON ? (
                                    <AverageTimeInspector
                                        onClick={() => {}}
                                        averageTime={step.average_conversion_time}
                                        disabled
                                    />
                                ) : null}
                            </div>
                        </header>
                        <div className="funnel-bar-wrapper">
                            {step.breakdown?.length ? (
                                step.breakdown.map((breakdown, index) => {
                                    const conversionRate = calcPercentage(breakdown.count, basisStep.count)
                                    const _previousCount = previousStep?.breakdown?.[index]?.count ?? 0
                                    const _dropoffCount = _previousCount - breakdown.count
                                    const conversionRateFromPrevious = calcPercentage(breakdown.count, _previousCount)
                                    const totalConversionRate = calcPercentage(breakdown.count, firstStep.count)
                                    const dropoffRateFromPrevious = 100 - conversionRateFromPrevious
                                    return (
                                        <Bar
                                            key={`${breakdown.action_id}-${step.breakdown_value}-${index}`}
                                            isBreakdown={true}
                                            breakdownIndex={index}
                                            breakdownMaxIndex={breakdownMaxIndex}
                                            breakdownSumPercentage={
                                                index === breakdownMaxIndex && breakdownSum
                                                    ? calcPercentage(breakdownSum, basisStep.count)
                                                    : undefined
                                            }
                                            percentage={conversionRate}
                                            name={breakdown.name}
                                            onBarClick={() => openPersonsModal(step, i + 1, step.breakdown_value)}
                                            layout={layout}
                                            popoverTitle={
                                                <span>
                                                    <PropertyKeyInfo value={step.name} />
                                                    {' • '}
                                                    {breakdown.breakdown}
                                                </span>
                                            }
                                            popoverMetrics={[
                                                {
                                                    title: 'Completed step',
                                                    value: breakdown.count,
                                                },
                                                {
                                                    title: 'Conversion rate (total)',
                                                    value: humanizeNumber(totalConversionRate, 2) + '%',
                                                },
                                                {
                                                    title: `Conversion rate (from step ${humanizeOrder(
                                                        previousStep.order
                                                    )})`,
                                                    value: humanizeNumber(conversionRateFromPrevious, 2) + '%',
                                                    visible: step.order !== 0,
                                                },
                                                {
                                                    title: 'Dropped off',
                                                    value: _dropoffCount,
                                                    visible: step.order !== 0 && _dropoffCount > 0,
                                                },
                                                {
                                                    title: `Dropoff rate (from step ${humanizeOrder(
                                                        previousStep.order
                                                    )})`,
                                                    value: humanizeNumber(dropoffRateFromPrevious, 2) + '%',
                                                    visible: step.order !== 0 && _dropoffCount > 0,
                                                },
                                                {
                                                    title: 'Average time on step',
                                                    value: humanFriendlyDuration(breakdown.average_conversion_time),
                                                    visible: !!breakdown.average_conversion_time,
                                                },
                                            ]}
                                        />
                                    )
                                })
                            ) : (
                                <Bar
                                    percentage={calcPercentage(step.count, basisStep.count)}
                                    name={step.name}
                                    onBarClick={() => openPersonsModal(step, i + 1)}
                                    layout={layout}
                                    popoverTitle={<PropertyKeyInfo value={step.name} />}
                                    popoverMetrics={[
                                        {
                                            title: 'Completed step',
                                            value: step.count,
                                        },
                                        {
                                            title: 'Conversion rate (total)',
                                            value: humanizeNumber(calcPercentage(step.count, firstStep.count), 2) + '%',
                                        },
                                        {
                                            title: `Conversion rate (from step ${humanizeOrder(previousStep.order)})`,
                                            value:
                                                humanizeNumber(calcPercentage(step.count, previousStep.count), 2) + '%',
                                            visible: step.order !== 0,
                                        },
                                        {
                                            title: 'Dropped off',
                                            value: dropoffCount,
                                            visible: step.order !== 0 && dropoffCount > 0,
                                        },
                                        {
                                            title: `Dropoff rate (from step ${humanizeOrder(previousStep.order)})`,
                                            value:
                                                humanizeNumber(
                                                    100 - calcPercentage(step.count, previousStep.count),
                                                    2
                                                ) + '%',
                                            visible: step.order !== 0 && dropoffCount > 0,
                                        },
                                        {
                                            title: 'Average time on step',
                                            value: humanFriendlyDuration(step.average_conversion_time),
                                            visible: !!step.average_conversion_time,
                                        },
                                    ]}
                                />
                            )}
                        </div>
                        <footer>
                            <div className="funnel-step-metadata">
                                <ValueInspectorButton
                                    icon={<ArrowRightOutlined style={{ color: 'var(--success)' }} />}
                                    onClick={() => openPersonsModal(step, i + 1)}
                                    disabled={!funnelPersonsEnabled}
                                >
                                    {step.count} completed
                                </ValueInspectorButton>
                                {i > 0 && step.order > 0 && dropoffCount > 0 && (
                                    <span>
                                        <ValueInspectorButton
                                            icon={<ArrowBottomRightOutlined style={{ color: 'var(--danger)' }} />}
                                            onClick={() => openPersonsModal(step, -(i + 1))} // dropoff value from step 1 to 2 is -2, 2 to 3 is -3
                                            disabled={!funnelPersonsEnabled}
                                            style={{ paddingRight: '0.25em' }}
                                        >
                                            {dropoffCount} dropped off
                                        </ValueInspectorButton>
                                        <span style={{ color: 'var(--primary-alt)', padding: '8px 0' }}>
                                            ({humanizeNumber(100 - calcPercentage(step.count, previousStep.count), 2)}%
                                            from previous step)
                                        </span>
                                    </span>
                                )}
                            </div>
                        </footer>
                    </section>
                )
            })}
        </div>
    )
}
