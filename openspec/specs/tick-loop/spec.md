# tick-loop Specification

## Purpose
Defines how the trader runs: a fixed-interval, stateless tick that operates only during regular exchange hours and always treats live broker state as the single source of truth.

## Requirements

### Requirement: Fixed-interval tick
The system SHALL evaluate positions and entries once per tick on a configurable fixed polling interval, and SHALL repeat for as long as the session is open when run in loop mode.

#### Scenario: Loop mode ticks repeatedly
- **WHEN** the trader runs in loop mode during the session
- **THEN** a tick executes, then the system sleeps for the configured interval, then ticks again

#### Scenario: Single-tick mode
- **WHEN** the trader runs in once mode
- **THEN** exactly one tick executes and the process exits

### Requirement: Tick order of operations
Each tick SHALL fetch fresh broker state, then check every open position against the exit rules, then scan for new entries, then place resulting orders.

#### Scenario: Exits before entries
- **WHEN** a tick finds a position that trips an exit rule and a qualifying entry candidate
- **THEN** the exit is placed before any entry is considered

#### Scenario: Snapshot failure
- **WHEN** the broker account snapshot cannot be fetched
- **THEN** the tick skips all trading actions and the next tick proceeds normally

### Requirement: Regular hours only
The system SHALL trade only between 9:30 AM and 4:00 PM America/New_York on weekdays, with no pre-market or after-hours trading.

#### Scenario: Outside hours
- **WHEN** a tick runs before 9:30 AM, after 4:00 PM ET, or on a weekend
- **THEN** no positions are managed and no orders are placed

#### Scenario: Inside hours
- **WHEN** a tick runs at 10:00 AM ET on a weekday
- **THEN** the tick proceeds to fetch broker state

### Requirement: No stored trading state
The system SHALL NOT persist or cache positions, entry prices, or timestamps between ticks or runs, and SHALL re-read positions, quotes, and account data from the broker every tick. A human-readable activity log MAY be written but SHALL NOT be read back to make decisions.

#### Scenario: Restart mid-session
- **WHEN** the process is stopped and restarted while positions are open
- **THEN** the next tick manages those positions using only broker data, with nothing to reload

### Requirement: Unlimited trades
The system SHALL NOT cap the number of trades per session.

#### Scenario: Repeated entries and exits
- **WHEN** entry and exit rules trigger many times in one session
- **THEN** every triggered order is placed without a trade-count limit
