# entry-gates Specification

## Purpose
Defines the deterministic checks and sizing rules a candidate must clear before a buy order is placed, none of which the AI can override.

## Requirements

### Requirement: SMA gate
A candidate SHALL pass only if its price is above the 200-day SMA, or between the 50-day and 200-day SMA; it SHALL fail if the 200-day SMA is unavailable.

#### Scenario: Above 200-day
- **WHEN** price is above SMA200
- **THEN** the gate passes

#### Scenario: Pulled back but above 50-day
- **WHEN** price is below SMA200 but above SMA50
- **THEN** the gate passes

#### Scenario: Below both
- **WHEN** price is at or below both SMA50 and SMA200
- **THEN** the gate fails

### Requirement: RSI gate
A candidate SHALL pass only if its 14-period RSI is above 30 and at most 70; unavailable RSI SHALL fail.

#### Scenario: Oversold
- **WHEN** RSI is 30 or lower
- **THEN** the gate fails

#### Scenario: Overbought
- **WHEN** RSI is above 70
- **THEN** the gate fails

### Requirement: Fibonacci retracement gate
A candidate SHALL pass only if its price lies within the 0.382 to 0.764 retracement zone of the last swing high/low over the configured lookback; a swing that cannot be determined from complete history SHALL fail.

#### Scenario: Inside zone
- **WHEN** price retraces 0.618 of the swing
- **THEN** the gate passes

#### Scenario: Truncated history
- **WHEN** fewer than the minimum number of daily bars are returned
- **THEN** the gate fails as unavailable

### Requirement: Forward P/E gate
A candidate SHALL pass only if its forward P/E is positive and below 90, where forward EPS is the next four quarters of consensus estimates, annualizing the mean of fewer estimates; zero or negative forward EPS SHALL fail.

#### Scenario: Reasonable valuation
- **WHEN** forward P/E is 35
- **THEN** the gate passes

#### Scenario: Negative earnings
- **WHEN** forward EPS is zero or negative
- **THEN** the gate fails

### Requirement: Conviction and sizing
The system SHALL buy only when the pick decision is buy with high or medium conviction, the symbol is not already held, and the sized order is at least the minimum trade size; order size SHALL be 25% of settled cash.

#### Scenario: Low conviction
- **WHEN** the pick has low conviction
- **THEN** no order is placed

#### Scenario: Already held
- **WHEN** the pick is a symbol already in the account
- **THEN** no order is placed

#### Scenario: Too little cash
- **WHEN** 25% of settled cash is below the minimum trade size
- **THEN** no order is placed

### Requirement: Opt-in EMA band report
The trend-analysis report SHALL additionally evaluate whether price sits inside the 8/21-day EMA band, and this check SHALL NOT affect live entries.

#### Scenario: Inside band
- **WHEN** price lies between EMA8 and EMA21 inclusive
- **THEN** the EMA band check passes in the report only
