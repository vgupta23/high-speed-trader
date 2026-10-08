# position-exits Specification

## Purpose
Defines the deterministic rules that close open positions: take-profit, stop-loss, and a pre-close flatten, none of which are decided by the AI.

## Requirements

### Requirement: Stop-loss
The system SHALL sell the full position immediately when its price is down 10% or more from its entry price, without waiting for confirmation.

#### Scenario: Stop-loss trips at threshold
- **WHEN** entry is 100.00 and current price is 90.00
- **THEN** the full position is sold with reason stop-loss

#### Scenario: Just above stop-loss
- **WHEN** entry is 100.00 and current price is 90.01
- **THEN** the position is held

### Requirement: Take-profit
The system SHALL sell the full position when its price is up more than 10% from its entry price.

#### Scenario: Above take-profit
- **WHEN** entry is 100.00 and current price is 110.01
- **THEN** the full position is sold with reason take-profit

#### Scenario: Exactly at take-profit
- **WHEN** entry is 100.00 and current price is 110.00
- **THEN** the position is held

### Requirement: Pre-close flatten
The system SHALL sell every open position once the time to the closing bell is within the configured close-out window (default 15 minutes), and SHALL NOT open new entries in that window.

#### Scenario: Close-out window
- **WHEN** the tick time is 3:50 PM ET and positions are open
- **THEN** all positions are sold and no new entry is placed

### Requirement: Exit thresholds are configurable
The take-profit and stop-loss percentages SHALL be configuration values and SHALL be applied from live broker entry prices.

#### Scenario: Custom threshold
- **WHEN** stop-loss is configured to 5% and a position is down 5%
- **THEN** the position is sold
