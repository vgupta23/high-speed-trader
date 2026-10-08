# Spec Delta

## Purpose

Defines how entry candidates are identified and described before the pick step: the seed universe, the day-change window, bull/bear tagging, and the trend and volume reads that accompany each candidate.

## ADDED Requirements

### Requirement: Universe is a floor, not a ceiling
The system SHALL scan every name in the seed universe each scan, and SHALL allow trading any liquid, actively-traded U.S. equity proposed outside the list if it satisfies the entry logic and broker tradability check.

#### Scenario: Off-list name
- **WHEN** the pick step proposes a liquid U.S. equity not in the universe and it passes all gates
- **THEN** it is eligible for entry

### Requirement: Day-change window
A universe name SHALL become a candidate only if its day change is within the configured window (default -10% to +10%, inclusive); names outside it SHALL be excluded as one-day outliers before the pick step.

#### Scenario: Inside window
- **WHEN** a name is up 6% on the day
- **THEN** it is a candidate

#### Scenario: Outlier excluded
- **WHEN** a name is up 25% on the day
- **THEN** it is excluded and never shown to the pick step

### Requirement: Bull or bear tagging
Each candidate SHALL be tagged bull when trading up on the day (momentum long) or bear when trading down (dip-buy candidate).

#### Scenario: Tagging
- **WHEN** one name is +3% and another is -4%
- **THEN** the first is tagged bull and the second is tagged bear

### Requirement: Deterministic trend classification
Each candidate SHALL carry a trend read computed deterministically from daily averages: bullish when the 10-day EMA is above the 21-day EMA and price is above both the 50-day and 200-day SMA; bearish when the 10-day EMA is not above the 21-day EMA and price is below both SMAs; otherwise neutral; unavailable when any input is missing.

#### Scenario: Bullish
- **WHEN** EMA10 > EMA21 and price is above SMA50 and SMA200
- **THEN** the trend is bullish

#### Scenario: Bearish
- **WHEN** EMA10 <= EMA21 and price is below SMA50 and SMA200
- **THEN** the trend is bearish

#### Scenario: Mixed
- **WHEN** EMA10 > EMA21 but price is below SMA200
- **THEN** the trend is neutral

#### Scenario: Missing input
- **WHEN** any of the five inputs is unavailable
- **THEN** no trend is assigned

### Requirement: Bearish trend is weighted down
The pick step SHALL be told each candidate's trend and SHALL be instructed to weight down momentum longs and dip-buys against a bearish trend.

#### Scenario: Prompt content
- **WHEN** the pick prompt is built
- **THEN** it includes each candidate's trend read and the instruction to down-weight bearish-trend names

### Requirement: Volume trend read
The system SHALL compute, on request via the trend-analysis report, the mean volume of the last 5 trading days versus the prior 5 and the On-Balance-Volume direction, and SHALL pass the trend-analysis volume gate only when volume change meets the configured minimum and OBV is not falling. This gate SHALL NOT affect live entries.

#### Scenario: Rising volume, rising OBV
- **WHEN** 5-day volume is up versus the prior 5 and OBV is rising
- **THEN** the volume trend gate passes

#### Scenario: Spike on falling OBV
- **WHEN** volume is up but OBV is falling
- **THEN** the volume trend gate fails

#### Scenario: Live entries unaffected
- **WHEN** a live tick scans candidates
- **THEN** the volume trend gate is not applied
