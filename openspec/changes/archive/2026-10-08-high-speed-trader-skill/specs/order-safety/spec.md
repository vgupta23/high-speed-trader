# Spec Delta

## Purpose

Defines the guardrails on what the trader may order and when: equities only, broker-verified tradability, and a master switch that keeps real orders off unless explicitly enabled.

## ADDED Requirements

### Requirement: Equities only
The system SHALL place orders only for stocks/equities and SHALL NOT trade options, futures, crypto, or other derivatives, even if the broker rail supports them.

#### Scenario: Non-equity instrument
- **WHEN** a pick or position refers to a non-equity instrument
- **THEN** no order is placed for it

### Requirement: Broker tradability check
The system SHALL verify with the broker that a symbol is a tradable equity before buying it.

#### Scenario: Untradable symbol
- **WHEN** the broker reports the symbol is not tradable
- **THEN** no buy order is placed

### Requirement: Live-trade master switch
The system SHALL place no buy or sell orders unless live trading is explicitly enabled by configuration; it SHALL default to disabled.

#### Scenario: Default
- **WHEN** live trading is not enabled
- **THEN** no order of any kind is placed

#### Scenario: Enabled
- **WHEN** live trading is enabled and a rule triggers
- **THEN** the order is placed

### Requirement: Simulation mode
Simulation mode SHALL force live trading off, evaluating positions and the pick and logging recommendations without placing orders.

#### Scenario: Simulation overrides enable
- **WHEN** simulation is requested while live trading is enabled
- **THEN** no orders are placed
