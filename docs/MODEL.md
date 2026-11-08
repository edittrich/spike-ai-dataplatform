# MODEL

Principles for designing a relational data model for a financial institution and implementing it in PostgreSQL (Supabase). The model is **built on the banking standards BIAN and FIBO**: BIAN decides the domain boundaries and which domain owns which entity; FIBO decides the names, definitions and relations of the entities.

**Version:** 1.0.0 (2026-11-08). The [change log](#change-log) at the end lists all versions.

**How to read this document:** This file assumes a project with a local Supabase (PostgreSQL) database, versioned migrations and automated integration tests. It contains no concrete model and no implementation. It states the principles that every concrete model must follow. Claude derives the concrete model from these principles, from the business domains in §3 and from the business scope that the user confirms. "Terms" defines the vocabulary and "Rules at a glance" lists the most important rules as a checklist. §2 is the basis in the standards and regulation, §3 the business domains, the bank structure and the reference data, §4 to §11 the principles; §12 describes the working process. The contents list below links every chapter.

Each principle has a short reason. The reasons come from experience with earlier models of the same kind; they describe problems that are expensive to fix after data exists.

**Contents**

- [Terms](#terms)
- [Rules at a glance](#rules-at-a-glance)
- [1. Purpose and scope](#1-purpose-and-scope): Starting the data model with Claude Code
- [2. Standards as the basis: BIAN and FIBO](#2-standards-as-the-basis-bian-and-fibo) (`STD`): Core principles · Roles of the two standards · Mapping BIAN to the model · Mapping FIBO to the relational model · Open world and closed world · Finding and verifying a FIBO concept · Deviations · Regulatory alignment · Standards tests
- [3. Business domains and reference data](#3-business-domains-and-reference-data) (`DOM`): Party & Customer · Deposit & Liquidity · Loan & Credit Risk · Reference data · Bank structure · Expected size
- [4. Modelling principles](#4-modelling-principles) (`MOD`): Core principles · Table classes · What becomes an entity · Keys · Supertypes and subtypes · Roles · Relationships · Attributes and null values · Code lists · Money and quantities · Derived data and views · Read interface · Physical design · Anti-patterns
- [5. Time and history](#5-time-and-history) (`HIS`): Core principles · Kinds of time · Validity of versions · The history operation · Set-based form · Change reasons · Change detection · Corrections and late data · Changing a versioned table · Business time · Events and snapshots in time · Querying history · Time zones and precision · Ending, erasure and undo · Time and history tests
- [6. Integrity](#6-integrity) (`INT`): Core principles · Levels of enforcement · Constraint catalog · Data types · Foreign keys · Checks · Rules across rows · Triggers · Transactions and consistency · Integrity and data quality · Data quality rules · Integrity tests
- [7. Naming](#7-naming) (`NAM`): General rules · Schemas · Tables by class · Views and functions · Columns · American English · Rates and ratios as fractions · Technical metadata · Constraints, indexes and triggers · Code values · Roles, migrations and other objects · Glossary and checks · Anti-patterns
- [8. Metadata and documentation](#8-metadata-and-documentation) (`MET`): General rules · Record metadata by table class · History metadata · Lineage · Model metadata · Data classification · Ownership, retention and quality · Descriptions · Generated documentation · Metadata tests
- [9. Security](#9-security) (`SEC`): Core principles · What the model protects against · Supabase specifics · Role model · Privilege matrix · Row-Level Security · Views and functions · Personal data · Connections, credentials and limits · Audit · Security tests
- [10. Migrations](#10-migrations) (`MIG`)
- [11. Test data and tests](#11-test-data-and-tests) (`TST`)
- [12. Working process](#12-working-process) (`PRO`)
- [Change log](#change-log)

**Normative language:** This document is a binding guideline. Its rules use the key words of RFC 2119:

| Wording | Meaning |
|---|---|
| A rule stated as a fact ("is", "has", "never", "only", "every"), or with **MUST** / **MUST NOT** | Mandatory. A model that breaks the rule is wrong, unless the deviation is recorded in the deviation register with the rule ID and its reason (§8) and approved in the entity list (§12) |
| **SHOULD** / **SHOULD NOT** | Strong recommendation. A different choice is allowed; it is recorded in the deviation register with the rule ID and its reason (§8) |
| **MAY** | Free choice. The project decides once and applies the decision everywhere; until it decides, the default applies (`PRO-04`) |

Words like "for example" introduce illustrations, not rules.

**Rule IDs:** Every rule has a stable ID of the form `<AREA>-<NN>`, for example `HIS-07`:

| Area | Chapter |
|---|---|
| `STD` | §2 Standards as the basis: BIAN and FIBO |
| `DOM` | §3 Business domains and reference data |
| `MOD` | §4 Modelling principles |
| `HIS` | §5 Time and history |
| `INT` | §6 Integrity |
| `NAM` | §7 Naming |
| `MET` | §8 Metadata and documentation |
| `SEC` | §9 Security |
| `MIG` | §10 Migrations |
| `TST` | §11 Test data and tests |
| `PRO` | §12 Working process |

- A numbered rule or a rule paragraph shows its ID at its start. A table that defines patterns, classes, codes or privileges has one ID for the whole table, shown in the line above it; a deviation from one row names the ID of the table and the row.
- IDs are stable. A changed rule keeps its ID; a new rule gets the next free number of its area, wherever it is placed; the ID of a removed rule is never used again.
- Deviations (§8), tests, reviews and the entity list refer to rules by their ID. Every test names the IDs of the rules it checks, so that a report can list the rules about the database that have no test (`TST-03`).

---

## Terms

| Term | Meaning |
|---|---|
| **Service domain** | BIAN's unit of business capability; it owns one control record (§2) |
| **Control record** | The central record a BIAN service domain manages, for example an agreement or a facility (§2) |
| **Owning domain** | The model domain that owns an entity and is the only one allowed to write it (§2, §9) |
| **FIBO concept** | The FIBO class an entity represents, identified by its IRI (§2) |
| **Deviation** | A recorded, justified departure from a standard or a rule of this document |
| **Entity** | A business thing with its own identity and lifecycle (§4) |
| **Table class** | The kind of a table, decided by how its data changes: identity, version, event, snapshot or reference (§4) |
| **Identity** | Table with the stable part of an entity: surrogate key, business key and the attributes that define the entity (§4) |
| **Version**, **version group** | Table with a group of changing attributes of one identity, with history (§4, §5) |
| **Event** | Table with immutable business facts at one point in time (§4) |
| **Snapshot** | Table with measured values of an entity, or of a combination of reference codes such as a currency pair, on a business date (§4) |
| **Reference** | Table with codes from a standard or a code list (§3, §4) |
| **Read interface** | The registered views and functions through which readers read a domain; the tables behind it may change (§4) |
| **Surrogate key** | Generated key without meaning; the target of all references (§4) |
| **Business key** | The key the business uses; unique and immutable (§4) |
| **Validity** | The half-open range in system time during which a version was the platform's state (§5) |
| **Current version** | The version with an open upper bound (§5) |
| **System time** | Time at which the platform held a state; set by the database when it writes (§5) |
| **Source change time** | Time at which the source system recorded a change; it decides the order of changes (§5, §8) |
| **Business time** | Time at which something applies or happens in the real world: effective dates, event times, value dates, snapshot dates (§5) |
| **History operation** | The operation that writes versions in loads: close the current version, open the next; per entity or set-based (§5) |
| **Correction** | A write that fixes wrongly recorded data: a new version with change reason `CORRECTION`, a correcting event or a restatement (§5) |
| **Change reason** | Code that says why a version exists (§5) |
| **Restatement** | A corrected snapshot row for the same entity and date (§5) |
| **Late change** | A delivered change that is older than the current version; it is not applied (§5) |
| **Rejection register** | Register of delivered rows that a load did not apply, with the reason (§8) |
| **Load run** | One registered write process; every row except reference data belongs to one (§8) |
| **Source system** | Registered origin of data, including the synthetic generator (§8) |
| **Record, process, model metadata** | Metadata about one row, one load run, one table or column (§8) |
| **Invariant** | A business rule that spans several rows or tables (§6) |
| **Data classification** | The protection level of a column, from public to special-category personal data (§8) |
| **Rule ID** | Stable identifier of a rule of this document, for example `HIS-07` (see "Rule IDs") |
| **Booking entity** | A legal entity of the bank that holds contracts and accounts in its books; an organization party in the role of booking entity (§3) |

---

## Rules at a glance

The most important binding rules, as a checklist for reviews. Each item names the rules it summarizes; the sections give the details and the reasons.

**Standards (§2)**

- [ ] Every identity, event and snapshot of a business domain has a BIAN service domain and a verified FIBO IRI, or a recorded deviation (`STD-07`, `STD-08`, `STD-09`, `STD-17`).
- [ ] Domain boundaries follow BIAN; only the owning domain writes an entity (`STD-03`, `STD-15`).
- [ ] Names, relations, roles and subtypes follow FIBO (`STD-05`, `STD-06`, `STD-18`).

**Modelling (§4)**

- [ ] The model is in third normal form; every fact is stored once (`MOD-01`).
- [ ] Every table has exactly one class, decided by the change pattern of its attributes (`MOD-04`, `MOD-12`, `MOD-16`).
- [ ] Identity and changing attributes are separate; references point to identities (and, between related facts, to events), never to versions or snapshots (`MOD-02`, `MOD-42`).
- [ ] Identities hold only the attributes that define the entity; attributes that can be recorded wrongly are versioned (`MOD-17`, `MOD-18`).
- [ ] Every entity has a unique, immutable business key next to its surrogate key (`MOD-03`, `MOD-25`, `MOD-28`).
- [ ] Events are immutable; daily measures are snapshots; derived values are views (`MOD-06`, `MOD-08`, `MOD-15`).
- [ ] Code lists are tables, never value lists in checks (`MOD-09`, `MOD-53`, `INT-22`).
- [ ] Every amount has a currency; not null is the default; no business defaults (`MOD-47`, `MOD-50`, `MOD-60`).
- [ ] Readers use the read interface; its changes are additive, and breaking changes go through a new view (`MOD-73` to `MOD-77`).

**Time and history (§5)**

- [ ] Validity is one half-open range in system time, set by the database; no active flag, no artificial end date (`HIS-01`, `HIS-11`, `HIS-12`, `HIS-17`).
- [ ] The versions of each version group are gapless and never overlap (`HIS-02`, `HIS-14`).
- [ ] History is written by the history operation, and the database rejects every write that would break it; every version has a change reason (`HIS-03`, `HIS-31`, `HIS-32`).
- [ ] Nothing is deleted, except by the defined retention, anonymization and undo operations (`HIS-04`, `HIS-77`).
- [ ] System time and business time are never mixed; every timestamp has a time zone (`HIS-05`, `HIS-06`, `HIS-08`).
- [ ] Changes to versioned tables keep the history readable and the change detection correct (`HIS-41` to `HIS-51`).

**Integrity (§6)**

- [ ] Every rule is enforced at the strongest possible level; wrong data is rejected, not repaired (`INT-07`, `INT-09`).
- [ ] Every relation is a foreign key without cascading actions; every foreign key to an identity or an event is indexed (`INT-04`, `INT-14`, `INT-16`).
- [ ] Every rule across rows is in the invariant register with its level and test (`INT-03`, `INT-25`).
- [ ] No forbidden data types (floating point, timestamps without time zone, enumeration types, …) (`INT-13`).

**Naming (§7)**

- [ ] Lower case `snake_case`, American English, whole words, approved abbreviations only (`NAM-01`, `NAM-06`, `NAM-07`, `NAM-17`).
- [ ] Table names start with their domain; the suffix of a column matches its data type (`NAM-13`, `NAM-16`, `NAM-35`).
- [ ] Rates and ratios are fractions; every constraint, index and trigger has an explicit name (`NAM-23`, `NAM-26`).

**Metadata (§8)**

- [ ] Every table and column is registered, described and classified in the same migration (`MET-04`, `MET-21`, `MET-23`, `MET-30`).
- [ ] Every row records its source; every row except reference data also records its load run and the role that wrote it (`MET-08`, `MET-09`).
- [ ] Delivered rows that a load does not apply are kept in the rejection register (`MET-14`).
- [ ] Documentation is generated from the database (`MET-33`).

**Security (§9)**

- [ ] Row-Level Security is enabled and forced on every table; the Supabase API roles get nothing (`SEC-01`, `SEC-09`, `SEC-27`).
- [ ] Privileges go to group roles only; one writing role per domain; no application uses an administrative role (`SEC-02`, `SEC-15`, `SEC-16`, `SEC-48`).
- [ ] Personal columns are readable only by roles with a documented need (`SEC-25`, `SEC-35`).
- [ ] Views and functions run with the caller's rights, apart from documented exceptions; no secrets in migrations (`SEC-03`, `SEC-04`, `SEC-34`, `SEC-36`).

**Tests (§11)**

- [ ] Every rule about the database has a test, and the tests prove that wrong data is rejected; rules about the working process are checked in reviews (`INT-10`, `TST-03`, `TST-04`).

**Checklist for every new table (Definition of Done)**

A table is done when every applicable item is checked. The items name the rules they come from.

- [ ] The table class is decided by the change pattern and recorded in the table register (`MOD-04`, `MOD-12`, `MOD-13`, `MOD-17`, `MET-21`).
- [ ] A table of a business domain has a BIAN service domain and a verified FIBO IRI, or an entry in the deviation register (`STD-07`, `STD-09`, `STD-17`, `STD-26`).
- [ ] The table name follows the pattern of its class; every column follows the column patterns (`NAM-13`, `NAM-14`, `NAM-16`).
- [ ] Primary key and unique business key exist, and so do the unique targets of composite foreign keys for subtypes and fixed currencies (`MOD-25`, `MOD-32`, `MOD-60`).
- [ ] Every relation is a foreign key without cascading action to an identity, a reference table or a related event; foreign keys to identities and events are indexed (`INT-04`, `INT-14`, `INT-15`, `INT-16`).
- [ ] Columns are not null unless the description defines the meaning of null; checks cover ranges, formats and the order of dates and contain no value lists (`MOD-47`, `MOD-48`, `INT-20`, `INT-21`, `INT-22`).
- [ ] Amounts have a currency and follow the sign rule; rates and ratios are fractions (`MOD-60`, `MOD-61`, `NAM-23`, `NAM-24`).
- [ ] The table has the record metadata columns of its class (`MET-08`).
- [ ] The table and every column have a description that follows the templates (`MET-30`, `MET-31`).
- [ ] The table register and the column register have complete entries, including classification, owner and retention class (`MET-21`, `MET-23`, `MET-27`, `MET-28`).
- [ ] Version tables: validity range, non-overlap constraint, index on current versions, guards and commit checks, history operation and the list of hash columns (`HIS-02`, `HIS-11` to `HIS-14`, `HIS-20` to `HIS-31`, `HIS-35`).
- [ ] Event tables: guard against changes and a unique business reference for idempotent loads (`MOD-06`, `HIS-64`, `INT-28`).
- [ ] Snapshot tables: key with snapshot date, documented interval, and decisions on restatements and non-business days (`MOD-07`, `HIS-59`, `HIS-61`, `HIS-63`).
- [ ] The read interface covers the table: current, derived and masked views as needed, registered and with a signature test (`MOD-73`, `MOD-74`, `MOD-77`).
- [ ] Row-Level Security is enabled and forced; policies and grants follow the privilege matrix; personal columns are protected (`SEC-21`, `SEC-25`, `SEC-27`, `SEC-28`).
- [ ] Every rule across rows that involves the table is in the invariant register with its level and test (`INT-24`, `INT-25`).
- [ ] Tests show that wrong writes are rejected, and the name, type and metadata tests pass (`INT-10`, `NAM-35`, `TST-04`).
- [ ] The generated documentation is updated (`MET-33`, `MET-34`).

**Decisions each project makes once (MAY rules)**

Each decision has a default. The default applies until the project records its own decision in the entity list (§12) and in `CLAUDE.md` (`PRO-04`):

| Decision | Rules | Default |
|---|---|---|
| Kind of UUID for surrogate keys | `INT-13` | Time-ordered UUID (version 7) where the database version supports it, otherwise a random UUID |
| Source key in versions; change hash in snapshots | `MET-08` | Versions record the source key; snapshots store no change hash |
| Per snapshot table: restatements and non-business days | `HIS-61`, `HIS-63` | Restatements are allowed; there is no snapshot on non-business days |
| Per versioned table: reopening an ended entity | `HIS-19` | Not allowed; a reopening is a new entity |
| Set-based form of the history operation; splitting large loads | `HIS-81`, `HIS-84` | Only the operation per entity; loads are not split |
| Provisional FIBO classes | `STD-25` | Allowed; the maturity level is recorded (`STD-26`) |
| Organizational units of the bank in addition to booking entities | `DOM-06` | Not modeled |
| Labels of code lists in other languages | `MOD-57` | English labels only |
| Mapping tables for source codes | `MOD-55` | One shared table with the source as part of the key |
| Partitioning and archiving of event and snapshot tables | `MOD-70` | None |
| Enforcing the read interface by privileges | `MOD-78` | Not enforced; the interface is a convention that reviews check |
| Row filters for roles | `SEC-32` | None |

---

## 1. Purpose and scope

The goal is a data model that is

- **grounded in industry standards**: every entity has a defined place in the BIAN service landscape and a defined meaning in FIBO,
- **correct by construction**: the database itself rejects invalid data,
- **historically complete**: every change can be traced, and history never breaks a reference,
- **self-describing**: the model documents itself inside the database, so that no second, hand-maintained description exists,
- **secure by default**: no data is reachable without an explicit decision.

Scope boundaries:

| In scope | Not in scope |
|---|---|
| The model: schemas, tables, constraints, views, history operations, metadata, security | Everything that uses the model after it exists |
| The interface for loading: load runs, record and process metadata, the history operation, the rules for corrections and the rules a load must follow (§5, §8) | The load logic itself: extracting data from source systems, transforming it, scheduling loads |
| Synthetic test data that follows every rule of the model (§11) | Real data from source systems |

### Starting the data model with Claude Code

**Requirement:** The project has a local Supabase (PostgreSQL) database, versioned migrations, an integration test suite and automated checks (locally, in CI or both). The local database runs and the integration tests are green.

1. Copy this file into the `docs` folder of the project.
2. Ask Claude to design the model, for example:
   ```text
   Design and implement the data model according to docs/MODEL.md.
   Business scope: the domains and reference data in §3 <plus or minus
   changes>. Follow the process in §12. Show me the entity list
   with the BIAN and FIBO mapping before you write any migration.
   Work on a feature branch and ask before you push.
   ```
3. Review the entity list (§12, phase 2). It is the cheapest point to change the model.
4. Let Claude implement, test and document the model, phase by phase.

---

## 2. Standards as the basis: BIAN and FIBO

BIAN and FIBO are the foundation of the model, not decoration added afterwards. Every domain, every entity and every name is derived from them first. Own decisions only fill the gaps the standards leave.

`STD-01` What each standard decides:

| Standard | What it decides in the model |
|---|---|
| **BIAN** (Banking Industry Architecture Network): reference architecture of a bank, a catalog of *service domains*, each owning one business capability and its *control record* | **Boundaries and ownership**: which domain owns an entity, which entity is the central record of a domain, which domains may only reference it |
| **FIBO** (Financial Industry Business Ontology, EDM Council): formal ontology of financial concepts with definitions and relations | **Meaning and structure**: name and definition of each entity, its relations, the split into supertypes and subtypes, the difference between a thing and the role it plays |
| **ISO and other code standards** (for example currencies, countries, industry classifications), which FIBO itself reuses | **Reference data**: the codes and their exact format |

### Core principles

1. `STD-02` **Standards come first.** Before an entity is designed, its BIAN service domain and its FIBO concept are known. *Reason:* the standards contain decades of agreed banking knowledge. Every bank and every tool that knows the standards understands a model built on them. Such a model also avoids the typical mistakes of an invented model, for example a role that copies the data of its party.
2. `STD-03` **Domain boundaries follow BIAN.** Related service domains form one domain of the model and one permission boundary in the database. An entity belongs to the domain that owns its control record. Other domains reference it; they never copy it.
3. `STD-04` **Every central entity is the control record of a service domain** or a direct part of it. An entity that no service domain owns is a modelling question and is discussed before it is created.
4. `STD-05` **Names and definitions follow FIBO.** An entity uses the FIBO term where it is clear. Where the bank's own term differs, the description names the FIBO term.
5. `STD-06` **Structure follows FIBO.** Relations, roles and subtypes are taken from the ontology, not invented. A role (for example customer) is a party in a role, not a kind of party; subtypes share the identity of their supertype.
6. `STD-07` **Every mapping is stored and stated.** The database records the BIAN service domain and the FIBO concept of every entity, and every description repeats them in a fixed form (§8).
7. `STD-08` **References are verified, not guessed.** FIBO identifiers (IRIs) are looked up in the current FIBO release (https://spec.edmcouncil.org/fibo/), BIAN service domain names in the current BIAN service landscape (https://bian.org). The releases used are recorded in the database.
8. `STD-09` **Deviations are explicit.** If FIBO has no matching concept or the model departs from it on purpose, the reason is recorded in the deviation register (§8). An entity without a mapping and without a reason is an error.

### Roles of the two standards

`STD-10` The standards answer different questions and are used at different moments of the design:

| Design question | Answered by | How |
|---|---|---|
| Which domains does the model have? | BIAN | Service domains grouped by the business capability they serve |
| Which domain owns an entity and may write it? | BIAN | The service domain whose control record the entity is, or is part of |
| What is the entity, and what is it called? | FIBO | The class whose definition matches the entity |
| Which relations, roles and subtypes does it have? | FIBO | Object properties, role patterns and subclasses of that class |
| Which attributes does it have? | FIBO first, then the business | Datatype properties of the class, completed by the bank's requirements |
| Which codes are valid? | ISO and other standards, FIBO individuals | Standard code lists; FIBO individuals for classifications |
| Which attributes must be filled? | The business | FIBO describes what *can* be said, not what must be stored (see "Open world and closed world") |

### Mapping BIAN to the model

1. `STD-11` **Find the service domain.** For every business concept in scope (§3), identify the BIAN service domain that is responsible for it in the current BIAN service landscape, with its business area and business domain.
2. `STD-12` **Find the control record.** Each service domain manages one control record (for example an agreement, an arrangement or a facility). The control record becomes an **identity** in the model (§4); its business key is the key that the service domain uses to refer to it.
3. `STD-13` **Map the parts of the control record.** BIAN describes the parts of a control record as behavior qualifiers and business objects. A part that has its own identity and lifecycle becomes its own entity owned by the same domain. A part without own identity becomes a version group, an event or a snapshot of the control record, according to its change pattern (§4).
4. `STD-14` **Group service domains into model domains.** Several service domains form one model domain when they manage the same kind of control record or work on the same entities (for example several kinds of accounts). The grouping is recorded with the domain.
5. `STD-15` **Ownership means write access.** Only the owning domain writes an entity. Other domains reference its identity and read it; they never store a copy of its attributes.
6. `STD-16` **Reference data has no owning service domain** in the model; it is shared by all domains and maintained by migrations. Reference data that is loaded regularly (exchange rates) has its own writing role (§9).
7. `STD-17` **Record the mapping.** Every identity, event and snapshot of a business domain records its service domain(s) in the table register (§8). Version tables inherit the mapping of their identity.

### Mapping FIBO to the relational model

`STD-18` FIBO is an ontology in OWL; the model is relational. The translation follows fixed rules:

| FIBO construct | Relational construct | Rule |
|---|---|---|
| Class with own identity and lifecycle, referenced by other things | **Identity table** (§4) | The FIBO class is recorded as the table's concept |
| Class without own identity (describes a part or a state of another thing) | Version group, event or snapshot of the thing it describes | Chosen by change pattern (§4) |
| Subclass with own attributes or relations | **Subtype** sharing the identity of its supertype (§4) | One subtype per subclass that the business needs |
| Subclass without own attributes | **Type code** in the supertype's identity | The code value records the subclass IRI |
| Disjoint subclasses | Exclusive subtypes | The immutable type code of the supertype prevents a second subtype (§4) |
| Role (a party playing a role in a context) | **Role entity** that references the party | Role-specific attributes live in the role, never in the party |
| Object property, single value | **Foreign key** on the side that has the property | Direction follows the property; the inverse property is not stored again |
| Object property, several values | **Association table** | The association becomes an entity if the relation has attributes or changes over time |
| Datatype property | **Column** | Data type as in the table below |
| Classifier class and its individuals (for example a sector, a status, a type) | **Reference table** (code list); individuals become rows | Each row records the IRI of its individual where one exists |
| Agreement, contract, arrangement | Identity of the agreement, with its parties as role references | The parties are never columns of names inside the agreement |
| Amount with currency (monetary amount) | Amount column plus currency (§4) | Never an amount without currency |
| Date period, date range | Two date columns or a business range (§5) | |
| Identifier class (an identifier issued by a scheme) | Business key column or identifier entity | An identifier entity is used when an entity has several identifiers from different schemes |

`STD-19` Data types of datatype properties:

| FIBO / XML schema type | Model type (§6) |
|---|---|
| `xsd:string` | text |
| `xsd:decimal` (amounts, rates) | exact decimal |
| `xsd:integer`, `xsd:nonNegativeInteger` | integer, with a check for non-negative values |
| `xsd:boolean` | boolean |
| `xsd:date` | date |
| `xsd:dateTime`, `xsd:dateTimeStamp` | timestamp with time zone |
| `xsd:duration` | integer with the unit in the name (§7) |
| `xsd:anyURI` | text with a format check |

### Open world and closed world

FIBO follows the *open world* assumption: it says what can be true, and a missing statement means "unknown". A database follows the *closed world* assumption: it says what is stored, and the schema decides what is required. The translation therefore follows three rules:

1. `STD-20` **FIBO restrictions are a guide, not a schema.** A cardinality restriction in FIBO ("has exactly one …") is a strong hint for a required relation, but the business decides whether the model requires it.
2. `STD-21` **The model may be stricter than FIBO,** never contradictory. A required column that FIBO does not mention is allowed; a relation that FIBO forbids is not.
3. `STD-22` **Reasoning is not reproduced.** Inferred facts (for example inferred class membership) are not stored. Where the model needs such a fact, it is an explicit column or a view with a documented rule.

### Finding and verifying a FIBO concept

1. `STD-23` **Search by definition, not by label.** A FIBO class matches when its definition matches the business meaning of the entity; a similar label is not enough.
2. `STD-24` **Take the most specific matching class.** If only a general class matches, take it and record that the model specializes it.
3. `STD-25` **Prefer released content.** FIBO marks its content with maturity levels (release, provisional, informative). Released classes SHOULD be used; a provisional class MAY be used with a note; an informative class MUST NOT be used while a released or provisional class matches.
4. `STD-26` **Record the full reference:** IRI, label, maturity level and FIBO release. The IRI is copied from the FIBO release, never typed from memory.
5. `STD-27` **Check after a FIBO release.** When the recorded FIBO release changes, every recorded IRI is checked against the new release; moved or deprecated classes are updated in a new migration.

### Deviations

`STD-28` Reasons for a deviation:

| Reason | Allowed | Handling |
|---|---|---|
| FIBO has no matching concept | yes | Nearest superclass, if one exists, plus a written reason |
| The FIBO concept is too general for the business need | yes | General class plus "specialized by the model" |
| The bank's or the regulator's term differs | yes, for the name only | Model name follows the business; the description names the FIBO term |
| Technical tables (versions, snapshots, metadata) | yes | Versions inherit the concept of their identity; snapshots and events are mapped like entities; metadata tables have no concept |
| The structure of a source system | **no** | The model follows the standards; mapping to the source happens in the load (§8) |
| Convenience, fewer joins, performance | **no** | Solved with views and indexes, never with a different model |

`STD-29` Every deviation is recorded in the deviation register (§8) with the rule ID and its reason, and reviewed in the entity list (§12).

### Regulatory alignment

Banking regulation sets requirements for risk data that the model supports by design. The model does not implement regulatory reports, but its structure must not prevent them.

**BCBS 239** (Basel Committee: principles for effective risk data aggregation and risk reporting):

| Principle | How the model supports it |
|---|---|
| Governance | Data owner and data steward per table; deviations and decisions recorded (§8) |
| Data architecture and IT infrastructure | One model based on BIAN and FIBO; one definition per concept; metadata, glossary and lineage in the database (§2, §8) |
| Accuracy and integrity | Rules enforced by the database; reconciliation of snapshots with events; automated loads with checks (§6) |
| Completeness | Completeness tests for versions and daily snapshots; every load run with row statistics (§5, §8) |
| Timeliness | Defined business-day cut-off; snapshot dates and load cut-offs recorded (§5, §8) |
| Adaptability | History and as-of queries for any date; code lists as data; new requirements as new migrations without loss of history (§4, §5) |
| Accuracy and comprehensiveness of reports | Reports can be reproduced for any past date from the first regular load on, because system time is never rewritten; corrections are visible as corrections (§5) |

**Data protection** (for example the GDPR): data classification, purpose-bound access, retention classes, erasure by anonymization (§5, §8, §9).

`STD-30` **Granular credit reporting as a plausibility check:** The attribute lists of granular regulatory credit reporting (for example AnaCredit in the euro area) are a good test of whether the credit domain is representative. During the entity list (§12), the main attribute groups are checked: counterparty identification (including the LEI), instrument and contract data, outstanding amounts and arrears, default and performing status, protection (collateral) and its value. A missing group is either added or recorded as out of scope. The model SHOULD NOT copy the reporting structure; it only checks that the data could be derived.

### Standards tests

In addition to §8 and §11, integration tests check:

- every identity, event and snapshot of a business domain has a BIAN service domain and a FIBO IRI or a recorded deviation; reference tables have a FIBO IRI where FIBO defines the concept;
- every recorded IRI has the form of a FIBO IRI and its maturity level and release are recorded;
- every version table has an identity table with a mapping;
- no domain writes to tables of another domain (checked through the grants of the writing roles, §9);
- reference rows that represent FIBO individuals record their IRI.

---

## 3. Business domains and reference data

The model covers three business domains and the reference data they share. Each domain is cut along BIAN service domains and described with FIBO concepts. The concepts below are business concepts, not tables: phase 2 of the working process (§12) turns them into entities, following the principles in §4 to §11.

### Party & Customer

`DOM-01` Scope of the domain:

| | |
|---|---|
| **Purpose** | Who the bank deals with, and in which role |
| **BIAN service domains** | Party Reference Data Directory (owns the party and its reference details), Customer Agreement (owns the customer relationship) |
| **FIBO modules** | Parties and party roles (FND), legal persons and legal entities (BE) |
| **Business concepts** | Party as the supertype of natural persons and organizations; addresses; identification documents and identifiers; the customer as a role that a party plays, with segment, KYC status and AML risk rating; the bank's own legal entities as organizations in the role of booking entity (see "Bank structure") |
| **Typical change patterns** | Identity and type of a party never change; names, addresses, verification states, segment, KYC status and risk rating change at irregular times and need history; birth and incorporation dates do not change, but are versioned so that wrong values can be corrected (§4) |

### Deposit & Liquidity

`DOM-02` Scope of the domain:

| | |
|---|---|
| **Purpose** | Money that customers hold at the bank |
| **BIAN service domains** | Current Account, Savings Account, Term Deposit |
| **FIBO modules** | Clients and accounts (FBC), accounting and currency amounts (FND) |
| **Business concepts** | Deposit account held by a customer in one currency; interest terms; overdraft facility; bookings on the account, including reversals; end-of-day balances and accrued interest |
| **Typical change patterns** | Account number, type and currency are fixed; status, interest terms and limits change at irregular times; bookings are events; balances and accrued interest are measured every business day |

### Loan & Credit Risk

`DOM-03` Scope of the domain:

| | |
|---|---|
| **Purpose** | Credit that the bank grants, and the risk it carries |
| **BIAN service domains** | Consumer Loan, Corporate Loan, Collateral Allocation Management |
| **FIBO modules** | Loans (LOAN), debt (FBC) |
| **Business concepts** | Loan application and its decision; loan agreement with principal, interest rate and maturity; repayment schedule with installments; disbursements and repayments; daily exposure with outstanding principal, accrued interest, arrears, days past due, non-performing status and risk stage; collateral, its allocation to one or more agreements, and its valuations |
| **Typical change patterns** | Contract terms change only with an amendment; the allocation of collateral changes at irregular times; disbursements, repayments and valuations are events; exposure, arrears and days past due are measured every business day; installment status and loan-to-value ratio can be computed |

### Reference data

`DOM-04` Reference data and its standards:

| Reference | Standard | Notes |
|---|---|---|
| Currencies | ISO 4217 | Code, name, number of minor units |
| Countries | ISO 3166-1 | Alpha-2 code as key, alpha-3 and numeric codes; AML high-risk classification based on the FATF lists, stored with its business period, because it changes with every FATF publication (§4, "Code lists") |
| Industries | NACE Rev. 2 | Sections and divisions as a hierarchy; risk level per industry, stored with its business period |
| Business calendar | Own, based on official holiday calendars | Business days and holidays per country or market; used for snapshot completeness and value dates (§5) |
| Exchange rates | Own time series, sourced from an official reference rate (for example a central bank) | Rate per currency pair, rate type and business date, as an exact decimal factor (units of the quote currency per unit of the base currency); kept as a snapshot (§4) in the reference data and loaded by its own writing role (§9), so that conversions (§4) use the rate of a defined date |
| Code lists | Own, mapped to FIBO where possible | One list per enumeration of the domains: party type and status, customer segment, KYC status, AML risk rating, address and identification types, verification status, account type and status, booking type, direction and status, rate type, accrual frequency, day count convention, facility status, application, agreement, installment and disbursement status, risk stage, collateral type and status, valuation method, risk level |

`DOM-05` Reference data uses a realistic subset where the full standard is large (for example a few dozen currencies and countries, including AML high-risk countries), and the complete list where it is small.

### Bank structure

A bank often consists of several legal entities (for example subsidiaries) and organizational units (for example branches). Contracts and accounts are held in the books of one of them. The model covers this from the start, because adding it later touches every contract.

`DOM-06` Scope of the bank structure:

| | |
|---|---|
| **Purpose** | Which part of the bank holds a contract or an account, and is responsible for it |
| **BIAN** | The service domains for the bank's own legal entities and organization in the reference data area (verify the current names in the BIAN service landscape) |
| **FIBO modules** | Legal entities and formal organizations (BE), with the LEI as identifier |
| **Business concepts** | Booking entity: a legal entity of the bank that holds contracts and accounts in its books. It is an organization party (Party & Customer) in the role of booking entity, so that the bank's own entities follow the same rules as every other party. Optionally the organizational unit (branch) that serves a contract |
| **Typical change patterns** | The booking entity of a contract is fixed when the contract is created; a transfer to another entity is a business event. The bank's legal entities change rarely; their changes are versions like those of every party |

Rules:

1. `DOM-07` **Every account and every agreement records its booking entity** as a reference from its identity to the booking entity role.
2. `DOM-08` **Amounts are aggregated per booking entity first.** Totals across entities are derived values.
3. `DOM-09` **One booking entity is enough for a representative model,** but the structure is present, so that the model can grow without changing every contract.

### Expected size

The model is **representative**: large enough to show every principle of this document in real use, small enough to stay understandable and reviewable as a whole. Every table class (§4) appears in every business domain where the business needs it, and every kind of invariant (§6) appears at least once. The model is not a complete banking data model.

`DOM-10` Guide values, counted from the concepts in this section and the rules in §4, §5 and §8:

| Area | Basis of the count | Tables (approx.) |
|---|---|---|
| Party & Customer | Party with versions and two subtype version groups; address, identification and customer, each as identity with versions; the booking entity role of the bank (see "Bank structure") | 11 to 13 |
| Deposit & Liquidity | Account as identity with versions; interest terms and overdraft as version groups; bookings as events; end-of-day balances as snapshots | 6 to 8 |
| Loan & Credit Risk | Application, agreement, installment and collateral, each as identity with versions; collateral allocation as association with versions; disbursements, repayments and valuations as events; daily exposure as snapshots | 13 to 15 |
| **Business tables** | | **30 to 36** |
| Reference data from standards | Currencies, countries with their AML classification periods, industries with their risk periods, business calendar, exchange rates | 6 to 8 |
| Code lists | The code lists named in "Reference data", plus change reasons (§5) and exchange rate types | 26 to 30 |
| Code mappings | Translation of source codes to model codes (§4), one per source or one shared table | 1 to 2 |
| Metadata registers | Table, column, reference, standard versions, model settings, source, load run, load statistics, rejections, field mapping, invariants, data quality rules, data quality results, retention classes, glossary, deviations, read interface (§8) | 16 to 18 |
| **Total** | | **about 75 to 95** |

Code lists and metadata registers are small and follow one pattern each; the part of the model that needs real design work is the 30 to 36 business tables.

In addition, the views and functions of the read interface (`MOD-73`): current, history and as-of access per identity with versions, the computed values of §4 and masked views (§9).

Rules for the size:

1. `DOM-11` **The entity list states the real numbers** per area (§12, phase 2).
2. `DOM-12` **Deviations of more than about 20 % from the guide values are explained** in the entity list. Fewer tables usually mean that change patterns were mixed (§4); more tables usually mean that the scope grew beyond §3.
3. `DOM-13` **New concepts are added only with a reason.** A concept that does not demonstrate a new principle or a new kind of relation is left out, even if a real bank would need it.
4. `DOM-14` **No concept from §3 is dropped** without the user's approval.
5. `DOM-15` **Test data has a representative volume as well.** It covers realistic histories, events and daily snapshots over several months. A full rebuild of the database with this data takes no more than a few minutes.

---

## 4. Modelling principles

This section defines how business concepts become tables, keys, relations and attributes. It applies to every table in the model.

### Core principles

1. `MOD-01` **Normalized core.** The model is in third normal form. Every fact is stored once, in the entity it describes. *Reason:* redundant facts drift apart.
2. `MOD-02` **Identity is separate from changing attributes.** Each entity has a stable identity that never changes: a surrogate key, its business key and the attributes that define the entity. Changing attributes are stored separately from the identity, with their history. All references point to the identity. *Reason:* if the key belongs to one state of an entity, every new state leaves the references on the old one.
3. `MOD-03` **Every entity has a business key.** The key that the business uses is unique and enforced by the database, next to the surrogate key.
4. `MOD-04` **Every table has exactly one class, and the change pattern decides the class** (see "Table classes").
5. `MOD-05` **Attributes with different change patterns never share a table.**
6. `MOD-06` **Events are immutable.** A correction is a new event that refers to the event it corrects. *Reason:* changing an event mixes up "the fact changed" with "we corrected the record".
7. `MOD-07` **Snapshots have a fixed interval and reconcile** with the events they can be derived from.
8. `MOD-08` **Derived values are not stored.** *Reason:* a stored derived value is wrong as soon as one of its inputs changes.
9. `MOD-09` **Code lists are data.** *Reason:* the list exists once, the meaning of each code is stored next to it, and adding a code is a data change.
10. `MOD-10` **Rules of the business are structure.** A rule that can be expressed as a relation is a relation. *Reason:* structure cannot be bypassed; application logic can.
11. `MOD-11` **Money always comes with its currency.**

### Table classes

`MOD-12` Whether data is "master data", "contract data" or "transaction data" does not matter. For every attribute, ask in this order:

| Question | Class |
|---|---|
| Does it define the entity, so that a different value would mean a different entity (type, currency, booking entity, business key)? | **Identity** |
| Does it describe something that *happened* at one point in time and stays true forever (a booking, a payment, a valuation, a decision)? | **Event** |
| Is it a value that is *measured* at a regular interval and may change every time (a balance, accrued interest, arrears, days past due)? | **Snapshot** |
| Does it change at irregular points in time because of a business decision or a change in the real world (a status, an address, terms, limits)? | **Version** (history, SCD Type 2) |
| Is it a code from a fixed list or an external standard? | **Reference** |
| Can it be computed from other stored data without loss? | **Not stored**; a view computes it |

*Reason:* attributes with different change patterns in one table produce either lost history or thousands of meaningless versions.

`MOD-13` Properties of the table classes:

| Class | Contains | Changes allowed | Key | Referenced by others |
|---|---|---|---|---|
| Identity | Surrogate key, business key, attributes that define the entity | Insert only | Surrogate key | Yes, always the target of references |
| Version | One group of changing attributes of one identity, with validity (§5) | Insert; closing of the current version (`HIS-31`) | Own surrogate key; one identity has many versions | Never |
| Event | One business fact with its time | Insert only | Surrogate key plus business reference | Only by related events (correction, counter-booking) and by allocation associations |
| Snapshot | Measures of one identity, or of one combination of reference codes (for example a currency pair), on one business date | Insert only (restatements, §5) | Identity or reference codes, plus snapshot date (plus restatement number) | Never |
| Reference | Codes with label, description and order | Data migrations only | The code itself (plus business period, `MOD-59`) | Yes, by code columns |

Rules:

1. `MOD-14` **Group attributes by change pattern.** Attributes that change together and at a similar rate form one version group. An identity may have several version groups when parts of it change independently (for example terms and status).
2. `MOD-15` **Check the grouping.** If a version would be created every day, the attribute is a snapshot. If a snapshot never changes between two dates, the attribute belongs to a version. If two attributes in one version group almost never change together, split the group.
3. `MOD-16` **Classes are never mixed.** A table never contains both fixed and changing attributes, both events and states, or both measured and decided values.
4. `MOD-17` **Identities hold only the attributes that define the entity.** Some attributes never change in reality but can be recorded wrongly, for example a birth date or an incorporation date. They belong to a version group, so that they can be corrected (§5). *Reason:* identities are insert-only; a wrong value in an identity cannot be fixed.
5. `MOD-18` **A wrong identity is replaced, not changed.** If a defining attribute was recorded wrongly, the entity is ended (§5) and a new identity is created that references the identity it replaces. A load that was wrong as a whole is undone instead (§8).
6. `MOD-19` **Metadata tables (§8) are outside the table classes;** their rules are in §8.

### What becomes an entity

`MOD-20` What a concept becomes:

| A concept becomes … | when … |
|---|---|
| an **entity with identity** | it has its own identity in the business (a business key or an identifier), its own lifecycle, and other things refer to it |
| a **version group** of another entity | it describes the changing state of that entity and has no identity of its own |
| an **event** | it is a fact that happened at one point in time |
| a **snapshot** | it is a measurement of an entity on a business date |
| a **code list** | it is a classification with a fixed, small set of values |
| a **column** | it is a single fact about one entity in one state |
| **nothing** (a view) | it can be derived from other stored data |

Rules:

1. `MOD-21` **Real-world things and agreements are entities;** their states are not. A status is never an entity; a contract is.
2. `MOD-22` **A concept that several entities share becomes its own entity** (for example an address that several roles use), not a copy in each of them.
3. `MOD-23` **Repeating groups become their own table.** No numbered columns (`phone_1`, `phone_2`), no lists in one column.
4. `MOD-24` **No generic structures.** No entity-attribute-value tables ("attribute name, attribute value"), no "one true lookup table" for all codes, no generic "object" or "item" tables. *Reason:* generic structures cannot be constrained, typed or understood without the data.

### Keys

`MOD-25` Keys by table class:

| Key | Rule |
|---|---|
| **Surrogate key** of an identity | UUID, generated by the database, without meaning; never shown to or typed by people; never changes |
| **Business key** of an identity | The key the business uses (a number the bank issues, a reference from outside, a code from a standard); unique, not null, immutable; stored in the identity |
| **Composite business key** | Allowed when the business defines it that way (for example a sequence number within a parent); enforced as one unique constraint |
| **Key of a version** | Own surrogate key; the version is identified by identity plus validity |
| **Key of an event** | Surrogate key plus a unique business reference of the fact |
| **Key of a snapshot** | Composite natural key: identity (or reference codes) plus snapshot date (plus restatement number) |
| **Key of a reference row** | The code itself (plus the business period for classifications that change over time, `MOD-59`); codes from standards exactly as the standard defines them |

Rules:

1. `MOD-26` **References use surrogate keys** (or codes for reference data), never business keys. *Reason:* business keys can be corrected; surrogate keys cannot be wrong.
2. `MOD-27` **No smart keys.** A key never encodes other facts (a branch, a year, a type). Such facts are separate attributes.
3. `MOD-28` **A business key never changes.** Sometimes the business really gives an entity a new number. Then the new number is either a new identity with a recorded link to the old one, or the old number is kept as a historic identifier.
4. `MOD-29` **Several identifiers from different schemes** (for example a national identifier and an international one) are stored in an identifier entity with the scheme as a code, not as a growing list of columns.

### Supertypes and subtypes

1. `MOD-30` **Subtypes share the identity of their supertype.** A subtype references the supertype's identity; it has no identity of its own.
2. `MOD-31` **The supertype carries an immutable type code.** The type is part of the identity, because an entity never changes its type. *Reason:* a type that can change is a status, not a type.
3. `MOD-32` **The type code is enforced.** A subtype can only belong to a supertype with the matching type code; a composite foreign key over identity and type code enforces this. The supertype identity has a unique constraint over its key and type code as the target of this foreign key.
4. `MOD-33` **Exclusive or overlapping, total or partial,** as the business and FIBO define it. Exclusive subtypes are enforced by the type code; totality ("every supertype has a subtype") is checked by a test.
5. `MOD-34` **Separate subtype tables** are used when a subtype has its own attributes or relations. Its defining attributes, if it has any, go into a subtype identity; its changing attributes go into subtype version groups. All of them use the key of the supertype. A subtype without own attributes is only a type code.
6. `MOD-35` **No single table with many optional columns** for different subtypes. *Reason:* it hides which column belongs to which type and makes "not null" impossible.

### Roles

1. `MOD-36` **A role is its own entity** that references the party playing it. One party can play many roles; each role is a separate entity with its own lifecycle.
2. `MOD-37` **Role-specific attributes live in the role** (for example a customer segment), never in the party.
3. `MOD-38` **A role has its own business key** when the business issues one (for example a customer number).
4. `MOD-39` **Agreements reference roles** when the business contracts with the role, and parties when the relation does not depend on a role. The choice follows FIBO.
5. `MOD-40` **A party's data is never copied into a role.** A role that needs a party's name reads it through the reference.

### Relationships

`MOD-41` Relationships by cardinality:

| Cardinality | Implementation |
|---|---|
| One to many | Foreign key on the "many" side |
| One to one | Foreign key with a unique constraint, or the same table if both sides always exist together and share their lifecycle |
| Many to many | Association table with two foreign keys and a unique constraint over both; an identity if the link never changes, an identity with versions if it can change or end |
| Relation with attributes | Association table that is an entity (identity, versions or events as needed) |
| Relation that changes over time | Versioned association with validity (§5), never an overwritten foreign key |
| Hierarchy within one entity | Parent reference to the same table; a check prevents self-reference, a constraint trigger prevents longer cycles |

Rules:

1. `MOD-42` **References point to identities.** An event or an allocation association MAY also reference an event, when one fact refers to another (a correction, a counter-booking, the allocation of a payment). Versions and snapshots are never referenced.
2. `MOD-43` **Mandatory relations are not null.** An optional relation is nullable only when "no related entity" is a real business state.
3. `MOD-44` **Relations are stored once.** The inverse direction is never stored as a second foreign key.
4. `MOD-45` **The direction follows ownership and FIBO.** The dependent side holds the reference.
5. `MOD-46` **Relations across domains** point only to identities of the owning domain and to reference data (§2).

### Attributes and null values

1. `MOD-47` **Not null is the default.** Every column is not null unless null has a defined business meaning.
2. `MOD-48` **Null means one thing per column.** The description states whether null means "not applicable" or "not known". If the business must tell both apart, a status code does it, not null.
3. `MOD-49` **Null never means zero, false or empty.** Booleans are always not null; empty strings are rejected by a check.
4. `MOD-50` **No business defaults.** A business value (a status, a type, an amount) has no default; the source must deliver it. Defaults are only used for technical values (keys, creation time, writing role). *Reason:* a default hides missing data.
5. `MOD-51` **One attribute, one meaning.** A column is never reused for different meanings depending on another column.
6. `MOD-52` **Units are fixed per column** and stated in its name and description (`NAM-16`, `MET-31`).

### Code lists

1. `MOD-53` **One reference table per code list.** Each list has a code, a label, a description, a sort order and an active flag, and MAY have a parent code for hierarchies and a FIBO IRI.
2. `MOD-54` **Codes are stable** (`NAM-30`). An outdated code is marked inactive; it is never deleted while data uses it.
3. `MOD-55` **Source codes are mapped, not copied.** Mapping tables translate source codes to model codes: one table per source, or one shared table with the source as part of the key (MAY). Loaders use the mapping; they never contain their own translation.
4. `MOD-56` **Hierarchical classifications** (for example industry sections and divisions) use a parent reference within the code list.
5. `MOD-57` **Labels are in English.** If other languages are needed, a separate label table holds one label per code and language.
6. `MOD-58` **"Unknown" is an explicit code** in lists where the business must record that a value is not known.
7. `MOD-59` **Classifications that change over time keep their history.** The classification of a reference value can change, for example the AML risk status of a country after a FATF publication. Such a classification is stored with a business period per value, so that the classification on any date can be found.

### Money and quantities

1. `MOD-60` **Every amount has a currency**, in the same row or in the identity it belongs to. If the currency of an entity is fixed (for example an account), it is part of the identity, and dependent rows reference identity and currency together, so that a different currency cannot be stored.
2. `MOD-61` **Flows are positive, stocks are signed.** Amounts of events (flows) are positive; their direction is a code (for example debit or credit). Amounts of snapshots (stocks, for example balances) carry a sign, and the description states the perspective (for example "positive = credit balance of the customer"). *Reason:* a booking has a direction; a balance can be negative.
3. `MOD-62` **Amounts in different currencies are never added** without a conversion. Converted amounts are derived values; the exchange rates come from the exchange rate reference data (§3), with their business date and rate type stated in the view that converts.
4. `MOD-63` **Amounts are in the major unit of the currency**; the number of minor units comes from the currency reference.
5. `MOD-64` **Quantities other than money** (counts, durations) state their unit in the name (`NAM-16`).

### Derived data and views

1. `MOD-65` **What can be computed is computed:** totals, balances that follow from events, statuses that follow from dates and payments, ratios.
2. `MOD-66` **Every derived value has one view.** Two views never compute the same value differently.
3. `MOD-67` **Views contain the time logic** (current state, as-of), so that queries do not repeat it (§5).
4. `MOD-68` **Views do not hide errors.** A view does not filter out rows that violate a rule; the rule is enforced in the tables.
5. `MOD-69` **Stored copies of derived values** (materialized results) are outside the core model. If one is needed, its refresh and reconciliation are documented and tested.

### Read interface

The views of a domain form its read interface: the stable surface through which the model is read. The tables behind it are the inside of the model and may change.

1. `MOD-73` **Readers use the read interface.** Every domain has a defined set of views. For access at a point in time, it also has functions with the point in time as parameter. Together they cover the current state (`HIS-65`), past states and history (`HIS-66`, `HIS-67`, `HIS-69`), derived values (`MOD-65`, `MOD-66`) and masked views for readers without access to personal data (`SEC-35`). Readers query these views and functions, not the tables; in the following rules, "view" includes these functions. Reference tables are part of the interface as they are, because their codes are stable (`NAM-30`). *Reason:* the tables can then change (`HIS-41` to `HIS-51`) without breaking any reader.
2. `MOD-74` **The interface is registered.** The interface register (§8) lists every view of the read interface. For each view, it records the status (active or deprecated), the date until which a deprecated view is kept and the migration that introduced the view. The column register also covers the columns of these views.
3. `MOD-75` **Interface changes are additive.** A view of the interface MAY get new columns. Existing columns keep their name, type and meaning, and the view keeps the meaning of its rows.
4. `MOD-76` **Breaking changes go through a new view.** Sometimes a column must change its name, type or meaning, or a view must change the meaning of its rows. Then a new view with a new descriptive name is created. The old view is marked as deprecated, kept until the recorded date and then removed. Names never carry version numbers (`NAM-09`).
5. `MOD-77` **Every interface view has a signature test.** A test compares the columns and types of every interface view with the interface register and the column register, so that a breaking change cannot happen unnoticed.
6. `MOD-78` **The interface is a convention, unless the project enforces it.** Views run with the rights of the caller (`SEC-34`), so readers also need select rights on the tables beneath; reviews check that reading services use only the interface. A project MAY enforce the interface by privileges instead. Readers then get rights only on the views. These views run with the rights of their owner as security barrier views, and the row filters of the policies move into them. This is a documented exception to `SEC-34` and `SEC-36`.

### Physical design

The logical model decides *what* is stored; the physical design decides *how* it is stored efficiently. Physical design never changes the logical model (§2, "Deviations").

`MOD-70` Rules of the physical design:

| Topic | Rule |
|---|---|
| **Indexes for keys** | Every primary key, business key and foreign key to an identity or an event has an index (§6) |
| **Indexes for time** | The non-overlap constraint of a version table serves lookups by entity and point in time; a partial index serves the lookup of current versions; event tables have an index on entity and event time; snapshot keys start with the entity and end with the date |
| **Other indexes** | Only for a known query pattern, with the pattern stated in the index description. No index "just in case" |
| **Partitioning** | Event and snapshot tables MAY be partitioned by date when their volume makes it useful. The partitioning key (event date or snapshot date) is then part of the primary key, of every unique constraint and of every foreign key that references the table, because PostgreSQL accepts unique constraints on a partitioned table only when they contain the partitioning key. Identity, version and reference tables are not partitioned |
| **Archiving** | Old partitions MAY move to cheaper storage, but stay part of the model and queryable until their retention period ends (§8). Archiving never deletes |
| **Large values** | Raw source payloads, if kept, are stored apart from the business columns |
| **Statistics and maintenance** | Database statistics are kept current after large loads; maintenance settings are part of the environment, not of the model |
| **Measured, not guessed** | Every physical optimization is based on a measured query plan and recorded with its reason |

`MOD-71` For the representative model with synthetic data (§3), indexes on keys and time are enough; partitioning and archiving are described here so that the model can grow without redesign.

### Anti-patterns

`MOD-72` Modelling anti-patterns:

| Avoid | Why | Instead |
|---|---|---|
| Foreign keys to versions | References break with every new version | References to identities |
| An "active" flag next to a validity | Two truths that drift apart | Validity only (§5) |
| A status as a type, a type as a status | Types cannot change, statuses must | Type in the identity, status in a version |
| A role that copies the party's data | Duplicated, inconsistent data | Role references the party |
| Entity-attribute-value tables | No types, no constraints, no meaning | Real columns |
| One lookup table for all codes | No foreign keys to a single list | One table per code list |
| Numbered columns, lists in one column | Not normalized, not queryable | Child table |
| Stored totals and statuses | Wrong after the next change | Views |
| Amounts without currency | Cannot be interpreted | Amount plus currency |
| Daily values in a version table | Thousands of meaningless versions | Snapshot |
| Business defaults | Missing data becomes invisible | No default; the source delivers the value |
| Smart keys | Facts hidden in keys | Separate attributes |
| Copying the structure of a source system | The model inherits its flaws | Model from the standards; map in the load |

---

## 5. Time and history

A financial data model must answer questions like these:

- *What was the customer's risk rating on the day the loan was approved?*
- *What did we know about this account at the end of last quarter?*
- *Which interest rate applies from next month?*

These questions need different kinds of time. This section defines them and states how history is kept, written, queried and ended. The metadata that records history is described in §8.

### Core principles

1. `HIS-01` **One representation of validity.** A version has exactly one validity, stored as one range. There is no extra "active" flag and no artificial end date in the far future. *Reason:* two representations of the same fact drift apart.
2. `HIS-02` **The database prevents overlapping history.** Two versions of the same version group of an entity can never be valid at the same time; a constraint enforces this, not the loader.
3. `HIS-03` **History is written in one way only.** A change of state closes the current version and opens the next one in a single transaction, through the history operation. Only the administrative operations (`HIS-77`) and the migrations that change versioned tables (`HIS-50`) write versions in another way. *Reason:* every additional way to write history is a way to corrupt it.
4. `HIS-04` **Nothing is deleted.** An entity ends by a final version, never by a delete. References never cascade a delete. *Reason:* regulated data has retention duties; one delete must never remove a full history silently. The only exceptions are defined below ("Ending, erasure and undo").
5. `HIS-05` **System time and business time are different things** and are never mixed in one column.
6. `HIS-06` **Every point in time has a time zone.** Timestamps are stored with time zone and handled in UTC; business dates are dates.

### Kinds of time

`HIS-07` Kinds of time:

| Kind | Question it answers | Where it is stored | Example |
|---|---|---|---|
| **System time** (recorded time) | Since when and until when did the platform hold this state? | Validity range of a version; creation time of every row | The address valid in the platform from March 3 until June 12 |
| **Source change time** | When did the source system record the change? | Record metadata of a version (§8) | The change of an address in the core system at 10:15 |
| **Business effective time** | From when does a change apply in the real world? | Business date or business period column of a version | A new interest rate effective from the first of next month |
| **Event time** | When did the fact happen? | Point-in-time column of an event | The moment a booking was made |
| **Value date** | From when does an amount count for interest and balance? | Business date column of an event | The value date of a booking |
| **Reporting date** | For which business day was a value measured? | Snapshot date (`as_of_date`) | The end-of-day balance of March 31 |
| **Load time** | When was the row written? | Record metadata (§8) | The load run of tonight |

Rules:

1. `HIS-08` **Each kind of time has its own column.** A column never means "event time, or load time if unknown".
2. `HIS-09` **System time is set by the database,** never by a loader; business times come from the business data. A loader never writes a business date into a validity range, and never writes load time into a business date.
3. `HIS-10` **Validity in system time is never in the future.** The lower bound of a version is at most the time of writing. Changes that apply in the future are business effective times (see "Business time").

### Validity of versions

1. `HIS-11` **Half-open range `[from, to)`.** The lower bound belongs to the version, the upper bound does not. The upper bound of one version equals the lower bound of the next one exactly. *Reason:* closed ranges create gaps or overlaps of one tick.
2. `HIS-12` **Open upper bound for the current version.** No `9999-12-31`, no `infinity` literal. A query for current versions tests for the open bound, not for a date.
3. `HIS-13` **Lower bound always set.** A version always has a start; ranges with an open lower bound or empty ranges are rejected by a check.
4. `HIS-14` **Gapless and non-overlapping per version group.** From the first version until the final version, every point in time is covered by exactly one version of each version group of the entity. An entity ends with a final version that carries an end status (change reason `END`), not with a gap. *Reason:* a gap cannot be told apart from missing data.
5. `HIS-15` **Full precision.** Bounds keep the full timestamp precision of the database; they are never rounded to seconds or days.
6. `HIS-16` **One system time per transaction.** All rows written in one transaction get the same system time: the transaction start time. One change therefore has one consistent point in time in all tables it touches. The system time comes from one function of the model. In tests, this clock MAY be moved forward through a setting that only a test role can use, so that several changes can be tested inside one rolled-back transaction.
7. `HIS-17` **The lower bound is the system time of the write.** The time at which the source recorded the change is stored separately as source change time (§8) and decides the order of changes; it never becomes the validity. *Reason:* only the platform's own time makes every past state of the platform reproducible.
8. `HIS-18` **The end is recorded once.** The end of an entity is recorded in the version group that carries its status; the other version groups keep their last version.
9. `HIS-19` **An ended entity stays ended.** After a version with change reason `END`, the history operation rejects further versions, unless the table register allows reopening for that table (MAY). A reopening is a version with change reason `CHANGE`.

### The history operation

Every versioned table is written by exactly one operation: one generated per table from a common pattern, or one generic operation. It follows the same steps for every table:

1. `HIS-20` **Serialize changes per entity,** for example with a transaction-level advisory lock on the key of the identity, so that concurrent changes to the same entity run one after the other. A row lock on the identity is not possible: row locks need an update right, and the writing role has none on identities (§9).
2. `HIS-21` **Read the current version.**
3. `HIS-22` **Compare** the new business attributes with the current version, using the change hash (see "Change detection"). If nothing changed, stop and write nothing.
4. `HIS-23` **Check the order:** the source change time of the new state must be later than the source change time of the current version; if a source delivers no change times, the order of its loads decides. Otherwise the change is late (see "Corrections and late data") and is not applied.
5. `HIS-24` **Close** the current version: set its upper bound to the system time of the write and record the load run that closed it (§8).
6. `HIS-25` **Insert** the new version with the system time of the write as lower bound, an open upper bound, its change reason, its source change time and its hash.
7. `HIS-26` **Commit** all steps in one transaction.

Rules:

1. `HIS-27` **Idempotent.** Running the same load twice creates no additional versions.
2. `HIS-28` **One change per entity and load.** If one load contains several changes of the same entity, only the latest by source change time becomes a version; the earlier ones are kept as superseded in the rejection register (§8). Two changes of the same entity with the same source change time are rejected as ambiguous. Without source change times, a load contains at most one change per entity, and further changes are rejected in the same way. *Reason:* all changes of one load share one system time. If intermediate states matter to the business, they are events (for example status change events), not versions.
3. `HIS-29` **Identity first.** A new entity is created as identity together with the first version of each of its version groups, in one transaction; an identity without its versions is never visible.
4. `HIS-30` **Same rules for all tables.** The operation is generated from one pattern or implemented once generically, never written differently per table.
5. `HIS-31` **The database guards the history.** The history operation runs with the rights of its caller (`SEC-36`), so the writing role could also insert and close versions directly. The database makes such a write as safe as the operation:
   - a guard rejects every change of a version except closing the current one, and it never closes a final version unless reopening is allowed (`HIS-19`);
   - at commit, constraint triggers check that every closed version has a successor that starts at its upper bound (`HIS-14`),
   - that every new identity has a first version in each of its version groups (`HIS-29`),
   - and that every new version starts at the system time of the write, unless its load run is a history load, seed load or migration (`HIS-38`).

### Set-based form

Calling the history operation once per entity is simple, but slow for large loads. The history operation therefore MAY also have a set-based form.

1. `HIS-81` **Set-based form.** For large loads, the history operation MAY also exist in a set-based form. It processes all changes of one load for one versioned table in a few statements, instead of one call per entity. Like the operation per entity, it is generated from one pattern or implemented once generically (`HIS-30`).
2. `HIS-82` **Same steps, same result.** The set-based form applies the steps `HIS-20` to `HIS-26` and the rules `HIS-27` to `HIS-31` to all entities of the load at once:
   - it keeps only the latest change per entity (`HIS-28`);
   - it puts late and superseded rows, and rows that reference a missing entity, into the rejection register (`MET-14`);
   - it drops changes whose hash equals the hash of the current version;
   - it locks the affected entities in a fixed order (for example sorted by key), so that two loads that run at the same time cannot block each other;
   - it closes all affected current versions in one statement and inserts all new versions in one statement, with one system time (`HIS-16`).

   For the same input, both forms produce exactly the same versions, closings, change reasons, hashes and rejections. A test loads the same data with both forms and compares the results.
3. `HIS-83` **Staging stays outside the model.** Delivered rows are collected in temporary tables of the load's own session. They are never model tables and are never visible to other sessions.
4. `HIS-84` **Large loads are split by entity.** A load that is too large for one transaction MAY be split into several load runs, each committed on its own (`MET-11`). All rows of one entity, in every table, stay in the same load run.

### Change reasons

`HIS-32` Every version records why it exists, with a code from a code list:

| Code | Meaning |
|---|---|
| `INITIAL` | First version of a new entity, or of a new version group of an existing entity (`HIS-48`) |
| `CHANGE` | Real change of the business state |
| `CORRECTION` | A previous version was wrong; the business state did not change |
| `HISTORY_LOAD` | Version with a lower bound in the past, written by an initial load of historic data, by the synthetic seed or by a migration that derives history (`HIS-47`) |
| `END` | Final version that ends the entity |

*Reason:* without a reason, a correction looks like a change of the customer's real situation, and reports over time become wrong.

### Change detection

1. `HIS-33` **A hash of the business attributes** is stored with every version. The history operation compares the hash of the new attributes with the hash of the current version and writes no new version when they are equal. *Reason:* repeated loads of unchanged data must not create versions.
2. `HIS-34` **The hash covers business columns only,** never metadata columns.
3. `HIS-35` **The covered columns are fixed per table** and recorded in the table register (§8). Adding a column to a version table changes the list in the same migration.
4. `HIS-36` **One hash function for the whole model.** It combines the name and the value of every covered column that is not empty. It uses a fixed order and an unambiguous text form for numbers, dates and times, so that the same attributes always give the same hash. Empty columns are left out, so that adding a column that is empty in existing versions does not change their hashes (see "Changing a versioned table").

### Corrections and late data

`HIS-37` Handling of corrections and late data:

| Situation | Handling |
|---|---|
| A delivered change is older than the current version (late change) | Not applied. It is kept in the rejection register with the reason `LATE` (§8) and counted by a timeliness rule (§6). If the business needs such states, they are modeled with business time or as events |
| The current version is wrong; the real state did not change | New version with change reason `CORRECTION` |
| A past version was wrong, but the current version is right | System time is not changed: the platform did hold the wrong state, and reports of that time stay reproducible. If the business must know the corrected past, the affected attributes carry business time, or the table is made bitemporal (see "Business time") |
| Historic data is loaded for the first time | Load of kind `HISTORY_LOAD`: versions with lower bounds in the past and change reason `HISTORY_LOAD`, written before any regular version of the entity |
| The synthetic test data needs histories | Load of kind `SEED`, with the same rules as a history load (§11) |
| An event was wrong | A correcting event that refers to the original (§4) |
| A snapshot was wrong | A restatement (see "Events and snapshots in time") |

Rules:

1. `HIS-38` **System time is never rewritten.** Lower bounds in the past are written only by history loads, seed loads and migrations that derive the history of a new version group (see "Changing a versioned table"). Even these write them only for version groups that have no regular version yet. The platform's states are reproducible from the first regular load on.
2. `HIS-39` **Corrections are visible as corrections.** A query over history can always tell a correction from a real change by the change reason.
3. `HIS-40` **Corrections made by the platform are rare and logged.** Each one belongs to a load run of kind `CORRECTION` with an input reference that explains it. Corrections that the source delivers as normal business facts (for example reversal bookings) arrive in regular loads.

### Changing a versioned table

After the release, versioned tables change through new migrations (§10), like every other table. Such a change must keep the history readable and the change detection correct.

1. `HIS-41` **History stays readable.** A migration never changes validity ranges and never removes versions. Every past state can still be queried after the change.
2. `HIS-42` **New columns get no invented history.** Versions that existed before the change stay empty in a new column, and its description states "not recorded before <migration>". If the business requires a value, a check makes the column mandatory for versions that start after the change.
3. `HIS-43` **New columns keep existing hashes valid.** The hash leaves out empty columns (see "Change detection"), so adding a column that is empty in existing versions does not change their hashes. The list of covered columns in the table register is updated in the same migration.
4. `HIS-44` **Renaming, retyping or removing a covered column recomputes the hashes.** The same migration recomputes the change hash of every version and updates the covered columns. *Reason:* otherwise the next load creates a new version for every entity.
5. `HIS-45` **A data type changes only without loss.** If a historic value cannot be converted exactly, the change is a new column, and the old column is deprecated.
6. `HIS-46` **Columns with history are deprecated, not dropped.** A column that holds historic values is marked as deprecated in the column register and in its description, and a check keeps it empty in new versions. It is dropped only when the retention of all its values has ended (§8).
7. `HIS-47` **Moving attributes to a new version group** (for example when two attributes turn out to change independently): the migration creates the new version group and derives its history from the existing versions. Consecutive versions with equal values are merged into one, so that the new group has no meaningless versions. The derived history repeats what the platform already held, so reproducibility is kept; it gets the change reason `HISTORY_LOAD`. The old columns are deprecated.
8. `HIS-48` **A new version group for existing entities** starts with a first version for every existing identity, written by the migration with its own system time and the change reason `INITIAL`. Columns without a known value stay empty, as in `HIS-42`.
9. `HIS-49` **A change of class** (for example an attribute that turns out to be measured every day) creates a table of the new class, which is filled from the change on. The old column is deprecated, and its history stays readable.
10. `HIS-50` **These migrations are an exception to the guards** (§6). They run as the owner, write only within load runs of kind `MIGRATION` (§8) and are tested.
11. `HIS-51` **Every such change is tested with a reload.** After the migration, loading the last delivered data again creates no new version.

### Business time

1. `HIS-52` **Business effective dates are attributes.** Sometimes a change applies in the real world from a different date than the date the platform learns about it. Then the version stores that date in a business column, for example the effective date of new terms. The validity range stays in system time.
2. `HIS-53` **Future changes are stored now.** A change that applies next month is a new version today, with a business effective date next month. Queries that need "the terms that apply on a date" use the business date, not the validity range.
3. `HIS-54` **Business periods are ranges when they must not overlap.** Sometimes the business forbids overlapping periods, for example two interest terms for the same account on the same day. Then the period is a business range with its own non-overlap constraint. It exists in addition to the validity in system time.
4. `HIS-55` **Contract dates are business attributes.** Start, maturity, opening and closing dates of contracts and accounts are business dates, not validity.
5. `HIS-56` **Bitemporal modelling only when needed.** System time already answers "what did we know at time X" and allows reports to be reproduced. A full bitemporal model uses two ranges with a combined constraint. It is added only when a requirement needs "what was true at business time X, as known at system time Y". Even then, it is added only to the tables that need it.

### Events and snapshots in time

1. `HIS-57` **Events have event time and, where relevant, a value date.** Both are business data; neither is a validity range.
2. `HIS-58` **Late events are normal.** An event with an event time in the past is inserted like any other event; no history needs to be rewritten.
3. `HIS-59` **Snapshots belong to a business day.** The snapshot date is a business date in the bank's business calendar, not a timestamp.
4. `HIS-60` **The cut-off is defined once.** The model defines once at which time and in which time zone a business day ends, for example with the end-of-day run in the bank's legal time zone. The model settings register records this definition (§8).
5. `HIS-61` **Non-business days are decided per snapshot table:** either no snapshot, or a carried-forward snapshot. The choice is recorded in the table register, and the completeness test (§11) uses it.
6. `HIS-62` **A business calendar is reference data.** Business days and holidays per country or market are kept as reference data (§3), so that completeness and value date rules can be checked.
7. `HIS-63` **A snapshot correction is a restatement:** a new row for the same entity and date with a higher restatement number; the original row stays. A view shows the latest restatement. Whether restatements are allowed is decided per snapshot table and recorded in the table register (§8).
8. `HIS-64` **Events and snapshots are loaded idempotently.** A row whose business reference or snapshot key already exists is skipped when it is identical and rejected when it differs. A different value for an existing snapshot date is accepted only as a restatement.

### Querying history

1. `HIS-65` **Current state through views.** Every identity with versions has a view of its current state (`NAM-15`). These views belong to the read interface (`MOD-73`).
2. `HIS-66` **State at a point in time ("as of")** selects the versions whose validity contains that point.
3. `HIS-67` **History over an interval** selects the versions whose validity overlaps the interval.
4. `HIS-68` **Joins across versioned entities use the same point in time on every side.** A join of two versioned tables needs a time condition on both sides. Without it, the join combines states that never existed at the same time.
5. `HIS-69` **Standard query helpers.** For every versioned table, the same helpers exist (current view, as-of access), named by the same patterns (`NAM-15`), so that nobody writes their own time logic.
6. `HIS-70` **Indexes support the time queries,** as described in the physical design (`MOD-70`).

### Time zones and precision

1. `HIS-71` **Points in time are stored with time zone** and written in UTC. Loaders set their session time zone to UTC.
2. `HIS-72` **Local times from sources are converted at the load,** with the source's time zone stated explicitly in the source register (§8). A time without a known zone is rejected.
3. `HIS-73` **Business dates have no time zone.** They belong to the bank's business calendar; converting them to timestamps is not allowed.
4. `HIS-74` **The bank's legal time zone is defined once** and used only for business-day cut-offs and presentation; the model settings register records it (§8).
5. `HIS-75` **Time measurement is not business time.** The duration of a load or a query is measured with the clock, not with the transaction timestamp, and is stored only in process metadata.

### Ending, erasure and undo

`HIS-76` Cases of ending, erasure and undo:

| Case | Handling |
|---|---|
| An entity ends in the business (account closed, contract paid off, customer left) | Final version with an end status and change reason `END`; the history stays |
| A retention period has expired | Removal of the entity with its full history by a dedicated retention operation, driven by the retention class (§8), logged as a load run |
| A data protection erasure request applies and no retention duty prevents it | Anonymization of the personal columns (classified in §8) in all rows of the entity, by a dedicated operation, logged as a load run; identity, keys and non-personal history stay |
| A load was wrong | Undo of the load run (§8) |

Rules:

1. `HIS-77` **Only these defined operations remove or overwrite data.** Each of them is restricted to administrators and runs as a function with the rights of its owner (`SEC-36`). It is logged as a load run and covered by a test. The guards of §6 make an exception only for these operations and for the migrations in "Changing a versioned table".
2. `HIS-78` **Anonymization keeps the structure.** Versions, validity ranges and relations stay, so that aggregates and history remain consistent. It recomputes the change hash of the rows it changes.
3. `HIS-79` **Retention and erasure are decided by metadata,** never by a value in a business column.
4. `HIS-80` **Retention respects references.** An entity is removed only when no entity that must still be kept references it. Dependent entities whose retention has also ended are removed first, in the same operation.

### Time and history tests

In addition to §8 and §11, integration tests check:

- no version has an open lower bound, an empty range or a lower bound in the future;
- the versions of each version group are gapless and do not overlap;
- every version group of every identity has exactly one current version; for an ended entity, it is the version with change reason `END`;
- every lower bound is the system time of its load, except in history and seed loads;
- the history operation writes nothing for unchanged data, does not apply late changes and keeps them in the rejection register;
- if the set-based form exists, it produces the same result as the operation per entity (`HIS-82`);
- after a migration that changes a versioned table, reloading the last delivered data creates no new version;
- a direct change of a version other than closing the current one is rejected, and so is a commit that leaves a closed version without a successor (`HIS-31`);
- two versioned tables joined in a view always share the same point in time;
- every point-in-time column has a time zone; no business date is stored as a timestamp;
- snapshots exist for every business day of the calendar where the table requires them;
- the retention, anonymization and undo operations change only the rows they are meant to change.

---

## 6. Integrity

Integrity means that the database accepts only data that is consistent with the model. This section defines which rules are enforced, by which mechanism, and how rules that the database cannot enforce alone are still guaranteed.

### Core principles

1. `INT-01` **The database enforces the rules, not the loader.** Every invariant that can be written as a constraint is a constraint. *Reason:* a rule that lives only in a loader is broken by the next loader or by a manual fix.
2. `INT-02` **A table is complete in its first migration.** Constraints, indexes, descriptions, metadata and security are created together with the table. *Reason:* adding them later means checking existing data first; a separate "hardening" step shows that the first version was incomplete.
3. `INT-03` **Rules across rows are written down and tested.** An invariant that spans several rows or tables is listed in the invariant register (§8). The database enforces it where that is reasonable, and a test checks it in every case.
4. `INT-04` **Every foreign key to an identity or an event is indexed.** *Reason:* these foreign keys are the paths of joins and checks; without an index, they scan the referencing table. Foreign keys to reference tables need no index of their own, because reference rows are never deleted and codes never change; they get one only for a known query pattern.
5. `INT-05` **Exact types.** Every column has the most specific type that fits its meaning (see "Data types").
6. `INT-06` **Every row is traceable to its origin.** Each row records where it came from and in which load run it was written; reference data records the migration instead. A bad load can then be found and undone (`MET-08`, `MET-09`).
7. `INT-07` **Wrong data is rejected, not repaired.** The database never corrects data silently (no truncation, no default for a missing business value, no trigger that "fixes" a value). The load fails and reports the reason.

### Levels of enforcement

`INT-08` Every rule of the model is enforced at the strongest level that is possible for it:

| Level | Mechanism | When it acts | Use for |
|---|---|---|---|
| 1. **Type** | Data type of the column | Every write | Kind of value (number, date, text) |
| 2. **Declarative constraint** | Primary key, unique, foreign key, not null, check, exclusion | Every write | Rules about one row, keys, relations, non-overlap |
| 3. **Constraint trigger** | Trigger that checks a rule and raises an error, deferred to the end of the transaction where needed | Every write or commit | Rules across rows that are cheap to check |
| 4. **Load check** | Check run by the load before it commits | Every load | Rules across many rows (sums, completeness of a load) |
| 5. **Test** | Integration test against the database | Every change of the model, and on loaded data | Every rule, including those above; reconciliation; completeness over time |

Rules:

1. `INT-09` **Use the strongest possible level.** A rule enforced by a test only, where a constraint would be possible, is a defect.
2. `INT-10` **Every integrity rule has a test,** whatever its level. The test proves that a violating write is rejected (levels 1 to 4) or that no violation exists (level 5).
3. `INT-11` **The level of every rule across rows is recorded** in the invariant register (§8).

### Constraint catalog

`INT-12` Constraint catalog:

| Constraint | Use for | Rules |
|---|---|---|
| **Primary key** | Every table | Surrogate key for identities, versions and events; composite natural key for snapshots; code (plus business period, `MOD-59`) for reference tables (§4) |
| **Unique** | Business keys; one-to-one relations; associations | Every business key has exactly one unique constraint; composite business keys are one constraint, not several |
| **Foreign key** | Every relation; every code column | To an identity, a reference table or, between related facts, an event (`MOD-42`); see "Foreign keys" |
| **Not null** | Every column without a defined business meaning of null | Default for every column (§4) |
| **Check** | Rules within one row: ranges, formats, order of two columns, conditional requirements | See "Checks" |
| **Exclusion** | Non-overlapping ranges per entity within a table: validity of versions (§5), business periods | Requires the extension for combined equality and range operators |
| **Partial unique index** | Uniqueness within a subset, for example one current version per identity | Also speeds up the lookup of that subset |
| **Constraint trigger** | Rules across rows (see "Rules across rows") | Only where no declarative constraint can express the rule |

### Data types

`INT-13` Data types by kind of value:

| Kind of value | Type | Rules |
|---|---|---|
| Surrogate key | UUID | Generated by the database; a time-ordered UUID where the database version supports it |
| Business key, reference, code | text | Format check where a standard defines the format |
| Name, free text | text | No empty strings; no length limit except where the meaning requires it |
| Amount | exact decimal with fixed scale | Enough precision for the largest expected amount and at least four decimal places |
| Rate, ratio | exact decimal | At least six decimal places; stored as a fraction (§7) |
| Exchange rate | exact decimal | Enough decimal places for the smallest quoted rate; quote currency per unit of base currency (§7) |
| Count | integer (or big integer where needed) | Check for non-negative values |
| Duration | integer | Unit in the name (§7); check for non-negative values |
| Business date | date | Never a timestamp |
| Point in time | timestamp with time zone | Never without time zone |
| Validity, business period | range of timestamps with time zone, range of dates | Half-open (§5) |
| Yes/no | boolean | Not null |
| Raw source payload | unstructured document type | Only for data that is kept as delivered and never queried or constrained |

Not used in the model:

- floating point numbers;
- the currency type of the database, because it depends on locale settings;
- fixed-length character types and length-limited text types (a check states a length when it matters);
- timestamps without time zone;
- auto-incrementing integer keys;
- database enumeration types (code lists are tables, §4);
- arrays and unstructured documents for business attributes.

### Foreign keys

1. `INT-14` **Every relation is a foreign key.** No relation is only implied by a column name.
2. `INT-15` **Target is an identity, a reference table or, between related facts, an event (`MOD-42`);** never a version or a snapshot.
3. `INT-16` **No cascading actions.** Deletes and updates of a referenced row are rejected (§5). Keys never change, so updates never need to cascade.
4. `INT-17` **Composite foreign keys have all columns not null,** so that a partly filled key cannot bypass the check.
5. `INT-18` **Every foreign key to an identity or an event leads an index,** or is the leading column of another index or constraint (`INT-04`).
6. `INT-19` **Foreign keys across schemas** follow `MOD-46`: they point only to identities of the owning domain and to reference data.

### Checks

1. `INT-20` **One rule per check,** with a name that says the rule (`NAM-26`, `NAM-27`).
2. `INT-21` **Typical checks:**
   - ranges (amounts of events greater than zero, `MOD-61`; rates within a plausible range; counts not negative);
   - formats of codes and identifiers from standards;
   - order of two columns (a start before an end, an opening before a closing);
   - conditional requirements (an end date is required when the status is "closed"; a reason is required when a decision is "rejected");
   - no empty strings.
3. `INT-22` **No enumerations in checks.** Lists of allowed values are code lists (§4); small technical lists in the metadata schema are the only exception (§8). A conditional rule MAY name a single code value (for example "a closing date is required for the status `CLOSED`"), because codes are stable (§7).
4. `INT-23` **Only immutable expressions.** A check never depends on the current time, the session or other rows.

### Rules across rows

`INT-24` Rules that involve several rows or tables are classified and enforced by kind:

| Kind | Example | Enforcement |
|---|---|---|
| **Structural** | A dependent row has the currency of its parent; a subtype matches the supertype's type | Composite foreign key (level 2) |
| **Temporal** | Versions do not overlap; at most one current version; a closed version has a successor | Exclusion constraint, partial unique index (level 2); constraint trigger at commit (level 3, `HIS-31`) |
| **Aggregate** | The sum of disbursements does not exceed the agreed principal | Constraint trigger, deferred to commit (level 3), or load check (level 4) |
| **Consistency between related rows** | A correcting event refers to an event of the same entity and has the opposite direction | Constraint trigger (level 3) |
| **Reconciliation** | A snapshot equals the sum of the events up to its date | Load check and test (levels 4 and 5) |
| **Completeness** | Every version group of every identity has a current version; every active entity has a snapshot for every business day | Constraint triggers at commit for versions (level 3, `HIS-31`); load check and test for snapshots (levels 4 and 5) |

Rules:

1. `INT-25` **Every such rule is in the invariant register** with its identifier, description, kind, level and test.
2. `INT-26` **Deferred checks run at commit,** so that a transaction can write several related rows in any order.
3. `INT-27` **A violation fails the whole transaction** and names the rule.

### Triggers

1. `INT-28` **Allowed uses:** guards that reject forbidden changes (changes of events, changes of versions other than closing, deletes), constraint triggers for rules across rows, and technical metadata that cannot be a default. Guards make an exception only for the administrative operations of §5 (retention, anonymization, undo) and for migrations that change versioned tables (§5). The exception is bound to the roles that run them: the owners of the administrative operations (`SEC-36`) and the owner of the model. Both exceptions are tested.
2. `INT-29` **Not allowed:** business logic, derivations, writes to other business tables, cascading changes, silent corrections of values. *Reason:* hidden logic in triggers makes the model unpredictable and hard to test.
3. `INT-30` **Every trigger is row-level, named by its rule (`NAM-26`), documented and tested.**
4. `INT-31` **Trigger functions are shared** where the rule is the same (for example one guard function for all event tables), and they use a fixed, empty search path with fully qualified names.

### Transactions and consistency

1. `INT-32` **A unit of work is one transaction.** Everything that belongs together (an identity with its first version; a booking with its counter-booking) is written in one transaction, so that readers never see half of it.
2. `INT-33` **A load commits only when all its checks pass** (§8). Readers see only data of successful loads.
3. `INT-34` **The history operation serializes changes per entity** with a lock on the entity (`HIS-20`).
4. `INT-35` **Consistency across domains** is kept by references to identities only. A domain never relies on a copy of another domain's data; rules across domains are tested.

### Integrity and data quality

`INT-36` Integrity and data quality compared:

| | Integrity | Data quality |
|---|---|---|
| Nature | Hard rules: the data is wrong if violated | Soft rules: the data is unusual, possibly wrong |
| Example | An amount without currency; overlapping versions | A balance far above the customer's usual range; a birth date 110 years ago |
| Effect | The write or the load is rejected | The data is stored; the finding is recorded per load (§8) |
| Where defined | Constraints, triggers, load checks | Quality checks in the metadata |

Rules:

1. `INT-37` **A hard rule is never weakened to a soft rule** to let a load pass. If the business accepts the data, the model changes in a new migration.
2. `INT-38` **Both kinds are registered** and both have tests.

### Data quality rules

Data quality rules are grouped by dimension. Every rule belongs to one dimension, has an identifier, a description, a threshold and a severity, and is stored in the metadata (§8).

`INT-39` Dimensions of data quality:

| Dimension | Question | Typical rules |
|---|---|---|
| **Completeness** | Is everything there that should be there? | Every active entity has a snapshot for every business day; optional columns are filled above an agreed rate; every expected source delivered a load |
| **Validity** | Do values follow the expected format and range beyond the hard rules? | Plausible ages, plausible interest rates for a product, identifiers with valid check digits |
| **Consistency** | Do related values agree? | Status and dates agree (a closed account has a closing date); the same fact delivered by two sources agrees |
| **Accuracy** | Does the data match the real world or an official figure? | Reconciliation with totals of the source system or the general ledger |
| **Timeliness** | Is the data current enough? | A load arrives before the agreed time; the latest snapshot is not older than one business day; few late changes per load (§5) |
| **Uniqueness** | Is every real thing stored once? | No two parties with the same identifiers under different business keys |

Rules:

1. `INT-40` **Severity decides the effect.** A *blocking* rule fails the load; a *warning* rule records a finding; an *information* rule only measures.
2. `INT-41` **Thresholds are explicit.** A rule states the share or number of failing rows it accepts.
3. `INT-42` **Results are kept per load run** (§8), so that quality can be followed over time.
4. `INT-43` **A rule that is never violated and is a hard business rule** is moved to integrity (§6) in a new migration.
5. `INT-44` **Synthetic test data contains deliberate quality findings** (but no integrity violations), so that every quality rule is shown to work (§11).

### Integrity tests

In addition to §8 and §11, integration tests check:

- every table has a primary key; every business key has a unique constraint;
- every relation and every code column has a foreign key; no foreign key points to a version or a snapshot, and foreign keys to events come only from events or allocation associations;
- no foreign key has a cascading action; every foreign key to an identity or an event leads an index;
- every column is not null unless its null meaning is documented;
- no column uses a forbidden type (see "Data types");
- no check contains a list of business values;
- every rule across rows is in the invariant register with a level and a test, and the test exists;
- for every constraint and trigger, a deliberately wrong write is rejected;
- no trigger writes to another business table.

---

## 7. Naming

Names are the interface of the model. People, queries, tests and generated documentation all depend on them, and a name is expensive to change once data and code use it. The conventions below are binding. A project records only its own choices (approved abbreviations, glossary, deviations) in the metadata registers (§8), and tests check every name (§11).

In the patterns, `<domain>` is the short name of a business domain and `<entity>` the name of an entity. `<event>` is the noun of a business fact, `<measures>` a group of measured values, and `<role>` the role a reference plays.

### General rules

1. `NAM-01` **Lower case `snake_case`, ASCII only.** Letters, digits and `_`; a name starts with a letter. *Reason:* PostgreSQL folds unquoted names to lower case; mixed case forces quotes in every query for ever.
2. `NAM-02` **Never quoted identifiers.** No spaces, no hyphens, no upper case, no special characters.
3. `NAM-03` **Well below the length limit.** PostgreSQL cuts names after 63 bytes without an error. Table names stay at about 30 characters or less, so that derived names (constraints, indexes, triggers) still fit. *Reason:* a truncated name can collide with another one and is hard to find.
4. `NAM-04` **No reserved or ambiguous words** as a full name: for example `user`, `order`, `group`, `type`, `value`, `date`, `time`, `timestamp`, `status`, `name`, `level`. Combine them with a qualifier instead (`account_status_code`, `legal_name`).
5. `NAM-05` **Business terms, from FIBO and the bank's glossary.** A name uses the term the business uses; where FIBO has a clear term, that term wins (§2). One concept has exactly one name in the whole model, and one name means exactly one concept.
6. `NAM-06` **Whole English words in American spelling.** All names, code values and descriptions use American English (see "American English" below).
7. `NAM-07` **Abbreviations only from an approved list.** The list is short and contains only abbreviations that are more common than the full word, for example `id`, `iso`, `iban`, `bic`, `lei`, `kyc`, `aml`, `nace`, `fx`. Everything else is written out (`number`, not `nr`/`no`/`num`; `amount`, not `amt`).
8. `NAM-08` **Singular nouns for tables,** because a table describes one kind of thing (`<domain>_<entity>`, not `<domain>_<entities>`).
9. `NAM-09` **No technical noise.** No prefixes or suffixes for the object kind (`tbl_`, `t_`, `_tab`, `v_`, `_view`) and no data types in names (`_str`, `_int`). No version numbers, no names of environments, projects, teams or persons, and no dates in object names.
10. `NAM-10` **No negations.** `is_verified`, not `is_not_verified`; `has_collateral`, not `no_collateral`.

### Schemas

`NAM-11` Schema patterns:

| Object | Pattern | Rule |
|---|---|---|
| Business domain | `<domain>` | One short noun per domain, singular, from the domain's BIAN/FIBO vocabulary |
| Reference data | one schema for all reference data | Shared by all domains |
| Model metadata | one schema for metadata and shared helper functions | Never mixed with business data |
| Extensions | the Supabase default schema for extensions | Never in a business schema |

`NAM-12` Nothing goes into the default schema `public` (`SEC-12`).

### Tables by class

`NAM-13` Every table name starts with its domain, so that it stays unique and readable without the schema (in logs, error messages, generated documentation). If the entity name already starts with the domain name, the domain is not repeated: the identity for the entity "party" in the domain `party` is `party`, not `party_party`.

`NAM-14` Table name patterns:

| Class (§4) | Pattern | Rule |
|---|---|---|
| Identity | `<domain>_<entity>` | The entity's FIBO or business term |
| Version | `<domain>_<entity>_version`, or `<domain>_<entity>_<attribute_group>_version` when an entity has several version tables | Always ends with `_version`, always starts with the name of its identity table |
| Event | `<domain>_<event>` | A noun for the fact that happened (booking, disbursement, repayment, valuation), not a verb and not a state |
| Snapshot | `<domain>_<entity>_<measures>` | Names the group of measures (balance, exposure); the date column is always `as_of_date` |
| Reference | `<domain>_<concept>` for a code list of one business domain; `<reference schema>_<concept>` for shared reference data; both in the reference schema | The concept the codes describe, for example a status, a type, a classification |
| Association (many-to-many) | the business noun for the relation, otherwise `<domain>_<entity_a>_<entity_b>` | A FIBO role or relation term is better than two joined table names |

### Views and functions

`NAM-15` Patterns for views and functions:

| Object | Pattern | Rule |
|---|---|---|
| View of the current state | `<identity_table>_current` | One per identity with versions |
| History view | `<identity_table>_history` | All versions with their validity, for history over an interval (`HIS-67`) |
| As-of function | `<identity_table>_as_of` | Returns the state at the point in time given as parameter (`HIS-66`) |
| View of computed values | `<table>_<purpose>` | Named by what it returns (`_status`, `_coverage`), no `v_` or `_view` |
| Masked view | `<view>_masked` | The view without personal columns or with masked values, for readers without access to personal data (`SEC-35`) |
| History operation | `<verb>_<table>`, with one fixed verb for each form (per entity, set-based) | The same verbs for all versioned tables, so that the operations are easy to find |
| Other functions | `<verb>_<object>` | A verb that says what the function does (`get_`, `calculate_`, `check_`) |
| Trigger function | `<purpose>` in the metadata schema when shared | Describes the rule, not the event (`forbid_change`, not `before_update`) |

### Columns

`NAM-16` Column patterns:

| Kind | Pattern | Data type | Rule |
|---|---|---|---|
| Surrogate key | `<table>_id` | UUID | The full table name without the schema, so that the key has the same name in every table |
| Foreign key | the name of the referenced key | as referenced | Same name on both sides, so joins read naturally |
| Foreign key with a role | `<role>_<referenced key>` | as referenced | When a table references the same table twice or the role matters (`citizenship_country_code`, `parent_<table>_id`) |
| Self-reference | `parent_<table>_id`, or a verb for the relation (`reverses_<table>_id`) | UUID | The name says the direction of the relation |
| Business key issued by the bank, sequence number | `<entity>_number` | text; integer for a sequence number within a parent | A number or identifier the bank assigns, or a position within a parent (for example an installment number) |
| Business key from outside | `<entity>_reference` | text | Reference delivered by another system or party |
| Code | `<concept>_code` | text | Always a foreign key to a reference table (for metadata columns: to a metadata register) |
| Name, title, label | `<qualifier>_name`, `_title`, `label` | text | Never just `name` (`NAM-04`) |
| Free text | `_description`, `_comment`, `_reason` | text | Says why the text exists |
| Amount | `<qualifier>_amount` | exact decimal | Always with a currency (§4); in major units of the currency |
| Currency | `currency_code`, or `<role>_currency_code` | text | ISO 4217 |
| Rate | `<qualifier>_rate` | exact decimal | Fraction, nominal annual unless named otherwise (see "Rates and ratios as fractions") |
| Ratio | `<qualifier>_ratio` | exact decimal | Fraction, same rules as rates |
| Exchange rate | `<qualifier>_exchange_rate` | exact decimal | Quote currency per unit of base currency; the only `_rate` that is not a fraction |
| Count | `<things>_count` | integer | Plural noun of what is counted |
| Duration | `<qualifier>_<unit>` | integer | The unit is part of the name (`term_months`, `past_due_days`) |
| Point in time | `<past participle>_at` | timestamp with time zone | What happened: `booked_at`, `approved_at` |
| Business date | `<noun>_date` | date | `value_date`, `maturity_date`, `birth_date` |
| Date of a snapshot | `as_of_date` | date | The same name in every snapshot |
| Business period | `<qualifier>_period` | range | For business validity that is part of the data |
| Boolean | `is_<adjective>`, `has_<noun>`, `can_<verb>` | boolean, not null | A question that the value answers with yes or no |

### American English

`NAM-17` The model uses **American English** for all names, code values, descriptions and generated documentation. *Reason:* FIBO, BIAN, ISO and the SQL standard are written in American English; one spelling makes names predictable and searchable.

`NAM-18` Spelling rules:

| Rule | American (use) | British (avoid) |
|---|---|---|
| `-ize` and `-yze` | `organization`, `authorization`, `capitalization`, `analyze`, `normalize` | `organisation`, `authorisation`, `analyse` |
| `-or` | `behavior`, `color` | `behaviour`, `colour` |
| `-er` | `center`, `meter` | `centre`, `metre` |
| `-se` for nouns | `license`, `defense` | `licence`, `defence` |
| Single `l` before a suffix | `canceled`, `modeling`, `labeled`, `traveled` | `cancelled`, `modelling`, `labelled` |
| `-og` | `catalog`, `dialog` | `catalogue`, `dialogue` |
| Other common words | `check`, `program`, `fulfillment`, `enrollment`, `judgment`, `gray` | `cheque`, `programme`, `fulfilment`, `enrolment`, `judgement`, `grey` |

`NAM-19` Banking terms follow American usage as well, where the two variants differ in meaning or form:

| Use | Avoid | Note |
|---|---|---|
| `check` | `cheque` | Payment instrument |
| `checking_account` | `current_account` | Use the BIAN name in the BIAN mapping (BIAN calls the service domain "Current Account"); the model name follows the American term |
| `postal_code` | `zip_code`, `postcode` | Neutral term, because addresses are international |
| `installment` | `instalment` | |
| `amortization` | `amortisation` | |

Rules:

1. `NAM-20` **Names taken from a standard keep the standard's form** in the mapping (for example a BIAN service domain name or a FIBO label in the metadata). The model's own names use American spelling.
2. `NAM-21` **Neutral international terms win over country-specific ones** (`postal_code`, not `zip_code` or `postcode`; `tax_identifier`, not `ssn`).
3. `NAM-22` **The glossary (§8) states the chosen spelling** of every term; a test checks names against a list of British spellings to avoid.

### Rates and ratios as fractions

`NAM-23` All rates and ratios are stored as **decimal fractions**: `0.035` means 3.5 %, `1.0` means 100 %. *Reason:* a fraction can be used in calculations directly (`amount * rate`); a mix of fractions and percentages is one of the most common sources of errors by a factor of 100.

`NAM-24` Rules for rates and ratios:

| Rule | Detail |
|---|---|
| Unit | Decimal fraction of 1. Never percent, per mille or basis points in a stored column. Exchange rates are not fractions; they use the suffix `_exchange_rate` |
| Names | `<qualifier>_rate` for rates, `<qualifier>_ratio` for the ratio of two quantities. No suffixes such as `_pct`, `_percent`, `_bps`, `_factor` |
| Period | A rate is a **nominal annual rate** unless its name says otherwise (`<qualifier>_monthly_rate`, `<qualifier>_daily_rate`). The period is also stated in the description |
| Basis | How a rate is applied (day count convention, compounding, fixed or variable) is a separate attribute or code, never part of the value |
| Data type | Exact decimal with at least six decimal places, so that a hundredth of a basis point (`0.000001`) can be stored |
| Sign | Negative rates are allowed where the business allows them (negative interest); the description says so |
| Range checks | Rates have a plausible range check (for example between `-0.1` and `1.0` for interest rates); ratios that can exceed 100 % (loan-to-value) have their own, wider range |
| Presentation | Conversion to percent or basis points happens only in presentation, never in stored data or views of the model |
| Spread and margin | A spread or margin is a rate as well and follows the same rules (`<qualifier>_spread_rate`, `<qualifier>_margin_rate`) |
| Descriptions | Every rate and ratio column states in its description: `Unit: fraction (0.01 = 1 %). Period: annual.` |
| Column register | The unit of every rate and ratio column is `fraction`; a test checks that every column ending in `_rate` or `_ratio` has this unit, except columns ending in `_exchange_rate` |

Examples: `interest_rate = 0.0425` (4.25 % per year), `penalty_interest_rate = 0.02`, `loan_to_value_ratio = 0.85` (85 %).

### Technical metadata

`NAM-25` Columns that describe the record and not the business carry the common prefix `md_`, for example the validity of a version, the creation time, the source system and the load identifier. The prefix makes them easy to exclude in comparisons, exports and documentation. Business columns never use this prefix.

### Constraints, indexes and triggers

`NAM-26` Every constraint, index and trigger gets an explicit name; nothing relies on generated names. The pattern follows the PostgreSQL defaults, so that explicit and generated names look the same:

| Object | Pattern |
|---|---|
| Primary key | `<table>_pkey` |
| Unique constraint | `<table>_<columns>_key` |
| Foreign key | `<table>_<columns>_fkey` |
| Check | `<table>_<rule>_check` |
| Exclusion constraint | `<table>_<rule>_excl` |
| Index | `<table>_<columns>_idx` |
| Unique or partial unique index | `<table>_<columns or rule>_uidx` |
| Trigger | `<table>_<rule>_trg` |
| Row-Level Security policy | `<table>_<role>_<command>` |

`NAM-27` `<columns>` lists the columns in order, `<rule>` names the rule in a few words (`no_overlap`, `positive_amount`). When a name gets too long, shorten the rule or column part, never the table part. *Reason:* an error message names the constraint; a clear name tells what was violated without looking it up.

### Code values

1. `NAM-28` **Upper case `SNAKE_CASE`, ASCII,** for example `ACTIVE`, `PARTIALLY_PAID`.
2. `NAM-29` **Meaningful, not numeric.** A code can be read without the reference table; numbers are only used where the external standard defines them.
3. `NAM-30` **Stable.** A code is never renamed and never reused for a different meaning; an outdated code is marked inactive.
4. `NAM-31` **Codes from standards are written exactly as the standard writes them** (ISO currency and country codes in upper case, NACE codes with their dots).
5. `NAM-32` **Labels and descriptions are for people;** they may change, the code may not.

### Roles, migrations and other objects

`NAM-33` Patterns for other objects:

| Object | Pattern | Example |
|---|---|---|
| Database group role | `<app>_<purpose>` | `<app>_reader`, `<app>_personal_reader`, `<app>_<domain>_writer`, `<app>_reference_writer`, `<app>_data_admin` |
| Login role of a service | `<app>_<service>` | |
| Personal login role of an administrator | `<app>_admin_<account>` | The account name of the person; the only object names that identify a person (exception to `NAM-09`) |
| Migration | `<timestamp>_<verb>_<object>` | `<timestamp>_create_<domain>_domain` |
| Source system code | upper case, like every code (see "Code values") | the same code for the same source in every load |

### Glossary and checks

1. `NAM-34` **The glossary is part of the model.** It is a register in the metadata schema (§8), filled by migrations. For every business term, it holds the definition, the FIBO concept, the name in the model and the approved abbreviation, if there is one. The glossary document is generated from this register.
2. `NAM-35` **Names are tested.** An integration test checks every name in the model against these rules:
   - pattern, character set and length,
   - no reserved words, no unapproved abbreviations,
   - table names start with their domain; version tables end with `_version` and start with their identity table,
   - **the suffix matches the data type**:
     - `_id`: UUID;
     - `_amount`, `_rate`, `_ratio`: exact decimal;
     - `_at`: timestamp with time zone; `_date`: date;
     - `_count`: integer; `_number`: text or integer;
     - `is_`, `has_`, `can_`: boolean;
     - `_code`: foreign key to a reference table or a metadata register;
   - foreign key columns have the name of the referenced key, or a role prefix in front of it,
   - every constraint, index and trigger follows its pattern.
3. `NAM-36` **Exceptions are deviations.** A name that breaks a rule on purpose (for example because a standard demands it) is recorded in the deviation register (§8) with the rule ID and its reason; the name tests read this register.

### Anti-patterns

`NAM-37` Naming anti-patterns:

| Avoid | Why | Instead |
|---|---|---|
| `id` as the key of every table | Ambiguous in joins and in result sets | `<table>_id` |
| `name`, `type`, `status`, `value`, `date` | Reserved or meaningless without context | A qualifier in front |
| `flag`, `ind`, `yn` | Says nothing about the meaning | `is_<adjective>` |
| `amount` without a currency | The value cannot be interpreted | Amount plus currency |
| `rate` without a fixed unit, `_pct`, `_bps` | 3.5 and 0.035 get mixed | Always a fraction, `_rate` or `_ratio` |
| `created`, `updated` without suffix | Unclear whether date or point in time | `created_at` or `created_date` |
| `cust_acct_bal_amt` | Private abbreviations | Whole words |
| `customer_v2`, `party_new`, `tmp_` | Versions and temporary states in names | Migrations and history in the data |
| Plural and singular mixed | Unpredictable names | Singular everywhere |
| Domain-specific synonyms (`client`, `customer`, `obligor` for one concept) | One concept with several names | One FIBO-based term |

---

## 8. Metadata and documentation

`MET-01` Metadata is part of the model, not an add-on. It answers four questions for every row and every object: *What does it mean?* *Since when and until when was it valid?* *Where does it come from?* *Who may use it and how long must it be kept?* The model keeps metadata on three levels:

| Level | Describes | Where it lives |
|---|---|---|
| **Record metadata** | One row: its validity, its origin, its load | Columns with the metadata prefix (§7) in every table |
| **Process metadata** | One load run: source, time, code version, result | Tables in the metadata schema |
| **Model metadata** | One table or column: meaning, class, standard mapping, classification, ownership, retention | Tables in the metadata schema and database descriptions |

`MET-02` The names below use the prefix `md_` (§7). The exact columns of each class are fixed once in the project and checked by tests.

### General rules

1. `MET-03` **The database is the single source of truth.** All metadata is stored in the database as data or as database descriptions, written by the same migration that creates the object. *Reason:* every hand-written copy of the schema drifts.
2. `MET-04` **Metadata is complete from the first migration.** A table without its record metadata columns, its registry entry, its column classification or its descriptions is incomplete (§6).
3. `MET-05` **Metadata is never business data.** Business columns never carry technical meaning, and metadata columns never carry business meaning. A business date (value date, effective date) is a business column, even if it looks like a technical timestamp.
4. `MET-06` **Metadata is written by the database wherever a default or the history operation can write it.** Creation time, writing role and closing information come from defaults and the history operation, not from the loader. *Reason:* a loader can forget or fake a value; a default cannot.
5. `MET-07` **Metadata is protected like the data it describes.** Model metadata is changed only by migrations. Process metadata is written only through defined operations: by the writing roles, by the administrative operations and by migrations.

### Record metadata by table class

`MET-08` Record metadata columns by class ("yes" means MUST, "MAY" means the project decides once per table, and "—" means the column does not exist in that class):

| Column | Meaning | Identity | Version | Event | Snapshot | Reference |
|---|---|---|---|---|---|---|
| `md_created_at` | When the row was written (system time, with time zone) | yes | yes | yes | yes | yes |
| `md_created_by` | Database role or service that wrote the row; default from the session | yes | yes | yes | yes | — |
| `md_load_id` | Load run that wrote the row (foreign key to the load register) | yes | yes | yes | yes | — |
| `md_source_system_code` | Source system code (foreign key to the source register) | yes | yes | yes | yes | yes |
| `md_source_key` | Key of the record in the source system | yes | MAY | yes | yes | — |
| `md_source_changed_at` | Time at which the source recorded the change; decides the order of changes (§5) | — | yes, if the source delivers it | — | — | — |
| `md_valid` | Validity range of the version (§5) | — | yes | — | — | — |
| `md_change_reason_code` | Why this version exists (§5) | — | yes | — | — | — |
| `md_record_hash` | Hash of the business attributes of the version, for change detection (§5) | — | yes | — | MAY | — |
| `md_closed_load_id` | Load run that closed the version; empty while it is current | — | yes | — | — | — |
| `md_restatement_number` | Number of the restatement of a snapshot; `0` for the original | — | — | — | if restatements are allowed | — |

`MET-09` Reference data records the migration that loaded it instead of a load run, and its source standard in the model metadata.

### History metadata

The rules for history are defined in §5. The metadata only records what these rules need, so that every history question can be answered from the data:

| History question | Answered by | Rules (§5) |
|---|---|---|
| Since when and until when was a state held? | `md_valid` | `HIS-11` to `HIS-17` |
| In which order did the source record the changes? | `md_source_changed_at`; source register | `HIS-17`, `HIS-23` |
| Why does this version exist? | `md_change_reason_code` and its code list | `HIS-32` |
| Did the attributes really change? | `md_record_hash`; covered columns in the table register | `HIS-33` to `HIS-36` |
| Which load opened and which load closed the version? | `md_load_id`, `md_closed_load_id`, load register | `HIS-24`, `HIS-25` |
| Which correction or history load wrote it? | Load kind in the load register | `HIS-38`, `HIS-40` |
| Which figure of a snapshot is valid? | `md_restatement_number`; restatement setting in the table register | `HIS-63` |
| Which delivered changes were not applied, and why? | Rejection register | `HIS-28`, `HIS-37` |

### Lineage

Lineage answers *where a value comes from and how it got there*, on four levels.

`MET-10` **Load level: the load register.** Every write to the model belongs to a registered load run, except reference data written by migrations (`MET-09`). A load run records:

| Information | Purpose |
|---|---|
| Load identifier | Referenced by `md_load_id` and `md_closed_load_id` |
| Source system | Which source delivered the data |
| Load kind | `FULL`, `DELTA`, `CORRECTION`, `HISTORY_LOAD`, `SEED`, `ROLLBACK`, `RETENTION`, `ANONYMIZATION`, `MIGRATION` |
| Status | `RUNNING`, `SUCCEEDED`, `FAILED`, `ROLLED_BACK` |
| Start and end time | Duration and order of loads |
| Data cut-off | The point in time up to which the source data is complete |
| Input reference | File name, extract identifier or query, with a checksum |
| Code version | The commit of the loader or generator that ran |
| Parameters | For example the random seed and volume of a generator |
| Triggered by | Role, service or person that started the run |
| Row statistics | Per table: rows inserted, versions closed, rows rejected |
| Affected entities | For administrative runs (undo, retention, anonymization): the entities they changed or removed |

Rules:

1. `MET-11` **The load run is registered before the first row is written,** in a transaction of its own, so that failed runs stay visible in the register. The data rows and the final status `SUCCEEDED` are committed together in one transaction. Every `md_load_id` references a registered run.
2. `MET-12` **Only rows of successful runs are visible to readers.** A run either succeeds completely or leaves no rows; a run with status `FAILED` has no rows in the model.
3. `MET-13` **A bad load can be undone, and the undo is itself a load.** Undoing removes the rows written by a run and reopens the versions it closed, found through `md_load_id` and `md_closed_load_id`. It is a technical operation for administrators only, recorded as a load of kind `ROLLBACK`. It is one of the defined exceptions to "nothing is deleted" (§5, "Ending, erasure and undo"), and it never touches rows of other runs. Undo works backwards: for an entity, only the latest load that wrote or closed its rows can be undone; later loads are undone first.
4. `MET-14` **Nothing delivered is lost silently.** A load may not apply a row: a rule rejects it, it is late or superseded within the load, or it references an entity that does not exist. Such a row is kept in the rejection register with its reason, its source key and its load run.
5. `MET-15` **Loads respect references.** A load writes identities and versions before the events and snapshots that reference them.

`MET-16` **Source level: the source register.** Every source system is registered with its code, name, owner and kind (core system, external provider, generator, manual entry). The register also records whether the source delivers source change times, the time zone of its local times (§5) and the format of its record keys. `md_source_system_code` and `md_source_key` together identify the original record of every row.

**Column level: mappings and derivations.**

1. `MET-17` For every real source, a mapping records which source field fills which column, with the transformation rule in words. The synthetic generator counts as a source and is documented the same way.
2. `MET-18` Every view records, in its description and in the model metadata, the columns it reads and the rule it computes.
3. `MET-19` Every snapshot that can be derived from events records the events it reconciles with (§4).

`MET-20` **Model level: schema history.** The registry records for every table and column the migration that introduced it and the migration that last changed it. Together with the migration history of the database, this shows which version of the model a row was written against.

### Model metadata

`MET-21` The metadata schema holds the following registers; each has a fixed structure, is filled by migrations and is checked by tests:

| Register | Content per entry |
|---|---|
| **Table register** | Schema and table; domain; class (§4); identity table of a version table; BIAN service domain(s); FIBO concept identifier (a missing one needs an entry in the deviation register, §2); data owner and data steward; retention class; snapshot interval and whether restatements are allowed; whether reopening after `END` is allowed; source systems; columns covered by the change hash; introducing and last changing migration |
| **Column register** | Schema, table or interface view, and column; data classification; personal data category; business key flag; unit (currency, fraction, days, months, …); FIBO property identifier where one exists; the migration that deprecated it, if it is deprecated (§5); introducing and last changing migration |
| **Reference register** | Every reference table with its standard, the standard's version, its source and the date it was last checked |
| **Standard versions** | BIAN, FIBO, ISO and NACE versions used by the model and the version of this guideline (`PRO-03`), with source and verification date |
| **Model settings** | Values that are defined once for the whole model, for example the business-day cut-off and the bank's legal time zone (`HIS-60`, `HIS-74`) |
| **Source register** | See lineage |
| **Interface register** | Every view and function of the read interface: status (active or deprecated), the date until which a deprecated view is kept, the migration that introduced it (`MOD-74`) |
| **Load register** | See lineage, including row statistics per table |
| **Rejection register** | Load run, target table, source key, reason (`REJECTED`, `LATE`, `SUPERSEDED`, `MISSING_REFERENCE`) and the delivered values as a raw payload, readable only by the data administrator (§9) |
| **Field mapping** | Source system, source object and field, target table and column, transformation rule |
| **Invariant register** | Every rule across rows (§6): identifier, description, enforcement (constraint, trigger or test only) and the name of the test that checks it |
| **Data quality rules** | Identifier, dimension, description, threshold, severity, table (§6); results per load run in the load register |
| **Retention classes** | Class, retention period, legal basis, the event that starts the period (for example the end of the customer relationship) |
| **Glossary** | Business term, definition, FIBO concept, name in the model, approved abbreviation |
| **Deviation register** | Rule ID, object, reason, approval (entity list or decision log) and date; covers deviations from every rule, including naming exceptions (§2, §7) |

`MET-22` Small technical value lists inside the metadata schema (for example the list of table classes) may be checks instead of reference tables, because they belong to the model's machinery, not to the business.

### Data classification

1. `MET-23` **Every column has exactly one classification level**, from public to special-category personal data:

   | Level | Meaning |
   |---|---|
   | `PUBLIC` | Public knowledge, for example codes from standards |
   | `INTERNAL` | Business data without personal reference |
   | `CONFIDENTIAL` | Business data that must not leave the bank, for example amounts and risk ratings |
   | `PERSONAL` | Personal data under data protection law |
   | `SPECIAL_CATEGORY` | Personal data with high risk, for example identity documents and birth dates |

2. `MET-24` **Personal data has a category** in addition to the level (identification, contact, financial, demographic, …), so that access, masking and deletion requests can be handled by category.
3. `MET-25` **Metadata columns are classified too.** `md_created_by` can identify a person.
4. `MET-26` **Every rule that depends on personal data reads the column register.** There is no second list of personal data columns in code.

### Ownership, retention and quality

1. `MET-27` **Every table has a data owner and a data steward,** recorded as roles, not as names of persons. The owner decides about access and changes; the steward maintains the content and its quality.
2. `MET-28` **Every table has a retention class.** The retention period and its starting event follow from the class, never from a value in the table itself.
3. `MET-29` **Quality results are metadata of the load.** Checks that run during or after a load (completeness, reconciliation, invariants) store their result per load run and per check. A result records the check identifier, the table, the outcome and the number of failing rows. A failed blocking check fails the load.

### Descriptions

1. `MET-30` **Every table, column, view and function has a database description**, written in the migration that creates or changes the object.
2. `MET-31` **Descriptions follow fixed templates:**

   | Object | Template |
   |---|---|
   | Table | `<Definition in own words>. Class: <class>. FIBO: <concept>. BIAN: <service domain>.` The FIBO and BIAN parts are left out where they do not apply (§2) |
   | Column | `<Meaning>. Unit: <unit>.` for amounts, rates, ratios and durations; `Code list: <reference table>.` for codes; `Standard: <standard>.` for codes from standards |
   | View | `<What it returns>. Reads: <tables>. Rule: <computation in words>.` |
   | Function | `<What it does>. Used by: <role or process>.` |

3. `MET-32` **Descriptions and registers agree.** A test compares the class, FIBO concept and BIAN service domain in each table description with the table register.

### Generated documentation

1. `MET-33` **Documentation is generated from the database** after every change: schema documentation per domain, entity-relationship diagrams, the glossary, the lineage from source fields to columns and views, and the list of invariants with their tests.
2. `MET-34` **Generated documentation is under version control.** A test fails when it is out of date.
3. `MET-35` **Nothing is documented only by hand.** Explanations that cannot be generated (design decisions, open questions) are kept in a short decision log and refer to the registers instead of repeating them.

### Metadata tests

In addition to §11, integration tests check:

- every table and column is in the registers, with all required fields for its class;
- every row of every data table has the record metadata of its class;
- every `md_load_id` and `md_closed_load_id` references a load run with status `SUCCEEDED`;
- versions are gapless and do not overlap; closed upper bounds equal the next lower bounds;
- every version has a change reason, and back-dated versions only have the allowed reasons;
- the stored hash matches the business attributes of each version;
- the row statistics of each load run match the rows in the tables and in the rejection register, taking later undo and retention runs into account;
- descriptions follow their templates and agree with the registers;
- every invariant in the invariant register has a test with the recorded name;
- every view and function of the read interface is in the interface register, and its columns are in the column register.

---

## 9. Security

Security is part of the model, not a layer added later. Every table, view and function is protected from the migration that creates it, and every access is the result of an explicit decision. This section defines the roles, privileges and policies of the model and the rules for personal data, connections and audit.

### Core principles

1. `SEC-01` **Deny by default.** Row-Level Security is enabled and forced on every table from its first migration (`SEC-27`). No table is reachable through the Supabase API roles, and the model's schemas are not exposed through the Supabase REST API. *Reason:* Supabase publishes tables over HTTP; one forgotten grant exposes data.
2. `SEC-02` **Least privilege.** Every role gets only the privileges its task needs: a reading role cannot write, a writing role writes only its own domain, and no application uses an administrative role.
3. `SEC-03` **Nothing runs with more rights than its caller.** Views and functions respect the privileges and policies of the user who calls them; default execute rights for everyone are revoked. The only exceptions are the documented ones in `SEC-35`, `SEC-36` and `MOD-78`.
4. `SEC-04` **No secrets in migrations.** Login roles and passwords are set outside the migrations, from the environment, by an idempotent step.
5. `SEC-05` **Personal data is classified at the source.** The column classification (§8) decides who may read a column, how it is masked and how it is erased; the retention class of its table decides how long it is kept (`MET-28`).
6. `SEC-06` **Defense in depth.** Every access passes several independent gates: schema usage, table or column privilege, Row-Level Security policy, and for writes the guards of §5 and §6. One mistake in one gate does not expose data.
7. `SEC-07` **Separation of duties.** Changing the model (migrations), loading data (writing roles) and removing or overwriting data (administrative operations, §5) are done by different roles.
8. `SEC-08` **Everything is traceable.** Every write is linked to a role and to a load run or, for reference data, to a migration (§8); every administrative operation is logged.

### What the model protects against

| Threat | Main protection |
|---|---|
| Public exposure through the Supabase REST or GraphQL API | Schemas not exposed; no privileges for the API roles; Row-Level Security without policies for them |
| An application with too many rights | Group roles per task; one writing role per domain; no application uses the owner or an administrative role |
| A compromised or faulty loader | Writes limited to its own domain; guards and commit checks reject every write that would break events or history (`HIS-31`) |
| Reading personal data without need | Column privileges and masked views driven by the column classification |
| Accidental destructive changes | No delete or truncate privileges; no cascading actions; administrative operations separated and logged |
| Leaked credentials | One credential per service, no shared passwords, rotation, timeouts, read-only default for readers |
| Changes to the model outside migrations | Only the owner role can create or change objects; no other role has create rights in any schema |

### Supabase specifics

1. `SEC-09` **API roles get nothing.** The Supabase roles for anonymous and authenticated API access have no usage right on the model's schemas and no privilege on any table, view or function. *Reason:* their keys are designed to be shipped to browsers.
2. `SEC-10` **The service role is never used by the model's applications.** It bypasses Row-Level Security and is meant for Supabase's own services.
3. `SEC-11` **No schema of the model is listed in the API schemas** of the Supabase configuration, so that neither the REST nor the GraphQL interface publishes it. Applications connect over the PostgreSQL protocol.
4. `SEC-12` **The default schema `public` stays empty** and nobody except the owner may create objects in it; Supabase's default privileges for the API roles in `public` must not reach the model.
5. `SEC-13` **The Supabase admin connection is used for migrations and administration only.** In Supabase, the default administrative user is not a full superuser; operations that need more rights (for example resetting its password) use the real superuser connection of the local stack and are documented.
6. `SEC-14` **The security and performance advisors** of the Supabase CLI and its database linter run after every migration (§10). Their findings are fixed or recorded in the deviation register (§8).

### Role model

`SEC-15` Roles of the model:

| Role | Kind | Purpose | Members |
|---|---|---|---|
| **Owner** | Administrative | Owns all objects of the model; runs migrations | Migration process only |
| **Reader** | Group, no login | Reads business data and metadata, without personal columns (levels `PERSONAL` and `SPECIAL_CATEGORY`) | Login roles of reading services |
| **Personal data reader** | Group, no login | Additionally reads columns classified as personal and special-category | Login roles of services with a documented need |
| **Domain writer** (one per domain) | Group, no login | Inserts into the tables of its own domain; runs their history operations; registers load runs | Login role of the loader of this domain |
| **Reference data writer** | Group, no login | Inserts regularly loaded reference data (exchange rates); registers load runs | Login role of the reference data loader |
| **Data administrator** | Group, no login | Runs the operations for retention, anonymization and undo (§5, §8); reads the rejection register | Personal login roles of administrators, never a service |
| **Service login** (one per service) | Login | Connects one service | Member of exactly the group roles the service needs |
| **API roles** of Supabase | Login (Supabase) | Not used by the model | No privileges |

Rules:

1. `SEC-16` **Privileges are granted to group roles only,** never to login roles and never to `PUBLIC`.
2. `SEC-17` **One login role per service.** Services never share a login; people never use a service login.
3. `SEC-18` **Group roles do not inherit from each other** unless the inheritance is part of this table; a login role is a member of the smallest set of groups.
4. `SEC-19` **Role names follow `NAM-33`** (`<app>_<purpose>`, `<app>_<service>`).
5. `SEC-20` **Roles are created idempotently** by a migration (group roles) or by the configuration step (login roles with passwords). The configuration step runs again after every rebuild of the database (`MIG-05`), so that a rebuild never leaves a login role without its password.

### Privilege matrix

`SEC-21` Privileges by role and table class:

| Table class / object | Reader | Personal data reader | Domain writer (own domain) | Domain writer (other domains) | Data administrator |
|---|---|---|---|---|---|
| Identity | select (non-personal columns) | select | select, insert | select (non-personal columns) | select, administrative operations |
| Version | select (non-personal columns) | select | select, insert, update of the closing columns only | select (non-personal columns) | select, administrative operations |
| Event | select (non-personal columns) | select | select, insert | select (non-personal columns) | select, administrative operations |
| Snapshot | select | select | select, insert | select | select, administrative operations |
| Reference | select | select | select | select | select |
| Views | select (masked where needed) | select | select | select | select |
| History operations | — | — | execute (own domain) | — | execute |
| Administrative operations | — | — | — | — | execute |
| Model metadata | select | select | select | select | select |
| Process metadata (load register, rejection register, quality results) | select (without rejected values) | select (without rejected values) | insert and update of their own load runs | — | select, update |

Rules:

1. `SEC-22` **Never granted to any role except the owner:** delete, truncate, references, trigger, create in a schema, and update on any column outside the matrix.
2. `SEC-23` **Schema usage is granted explicitly** per role and schema.
3. `SEC-24` **Default privileges are set** for every schema, so that objects created later get the same privileges without a new grant and never become executable or readable by `PUBLIC`.
4. `SEC-25` **Column privileges implement the classification.** The reader gets select only on columns below the personal levels; the matrix is generated from the column register (§8), not written by hand.
5. `SEC-26` **The reference data writer** has select on reference data, insert on regularly loaded reference data (exchange rates) and the process metadata rights of a writer, and nothing else.

### Row-Level Security

1. `SEC-27` **Enabled and forced on every table,** so that also the table owner is subject to the policies unless it explicitly bypasses them for administration.
2. `SEC-28` **Explicit policies for every role and command** that the privilege matrix allows. A table privilege without a policy gives no rows; a policy without a privilege gives no access.
3. `SEC-29` **Policies are generated from the metadata** (table class, domain, roles) by a loop in the security migration, so that no table is forgotten and all tables of one class have the same policies.
4. `SEC-30` **Simple policy expressions.** A policy uses columns of its own row and stable expressions; it does not query large tables. *Reason:* policies run for every row and must stay fast and predictable.
5. `SEC-31` **Version tables allow updates only on current versions,** as a second gate next to the guard of §5. The roles that run the administrative operations have their own policies.
6. `SEC-32` **Row filters where the business needs them.** Sometimes a role must not see some rows, for example the rows of a restricted customer segment. Then a policy filters on a column of the row, and the table register documents the filter.
7. `SEC-33` **Policy names follow `NAM-26`** (`<table>_<role>_<command>`).

### Views and functions

1. `SEC-34` **Views run with the rights of the caller.** Every view is created so that the caller's privileges and policies apply, never the owner's, except for the documented exceptions (`SEC-35`, `MOD-78`). *Reason:* otherwise a view bypasses Row-Level Security.
2. `SEC-35` **Masked views for general readers.** For tables with personal columns, a view for the reader leaves those columns out or shows values that do not need them (for example a flag computed from non-personal columns). It is generated from the column classification. A view with the caller's rights cannot read columns that the caller may not read. Masking that needs the original value (for example the first letter of a name) therefore needs a view with the owner's rights; such a view is a documented exception, created as a security barrier view and reviewed like an administrative function.
3. `SEC-36` **Functions run with the rights of the caller** by default. A function that runs with the rights of its owner is allowed only for a narrowly defined administrative operation. Its owner has exactly the rights the operation needs. It has explicit execute grants, validates its inputs and is reviewed.
4. `SEC-37` **Fixed, empty search path and fully qualified names** in every function and trigger function.
5. `SEC-38` **Execute rights are revoked from `PUBLIC`** for every function of the model, including future ones (default privileges), and granted explicitly per role.

### Personal data

1. `SEC-39` **The registers decide** (`MET-23`, `MET-24`, `MET-28`): the column register holds the classification level and the personal data category, the table register the retention class.
2. `SEC-40` **Business keys are not personal data.** A national identifier or an e-mail address is never a key or a foreign key. *Reason:* keys appear in references, logs and error messages.
3. `SEC-41` **Error messages and logs avoid personal values.** Constraints are designed so that their error details show keys and codes, not personal attributes. Log settings in shared environments do not record statement parameters.
4. `SEC-42` **Descriptions, metadata and documentation contain no personal data,** only its structure.
5. `SEC-43` **Test and development data is synthetic** (`TST-01`); production data is never copied into a development database.
6. `SEC-44` **Erasure and anonymization** follow §5 ("Ending, erasure and undo") and are run only by the data administrator.
7. `SEC-45` **Uniqueness of personal identifiers** (for example identity document numbers) SHOULD be enforced on a hash of the normalized value, so that a violation does not show the value in an error message (`SEC-41`).

### Connections, credentials and limits

1. `SEC-46` **One credential per login role**, stored only in the environment (`.env`, never in the repository), with a password hashing method of the current standard (SCRAM).
2. `SEC-47` **Credentials are rotated** by re-running the idempotent configuration step with new values.
3. `SEC-48` **Applications never connect as the owner,** the Supabase administrative user or the service role.
4. `SEC-49` **Encrypted connections** for every connection that leaves the local machine.
5. `SEC-50` **Limits per role:** a statement timeout, an idle-in-transaction timeout and a connection limit for every login role; read-only transactions by default for reading roles.
6. `SEC-51` **Local services bind to localhost only,** so that the local database and its tools are not reachable from the network. The Supabase CLI publishes its ports on all interfaces by default. The project prevents this, for example with a Docker network whose default host address is `127.0.0.1`, and checks the bindings after the start.

### Audit

1. `SEC-52` **Every row records its writing role and load run** (`INT-06`, `MET-08`); reference data records its migration instead (`MET-09`).
2. `SEC-53` **Every administrative operation is a logged load run** with the person or process that started it and an input reference that explains it.
3. `SEC-54` **Changes to the model happen only through migrations;** the migration history of the database is the audit trail of the schema.
4. `SEC-55` **Read access to personal data is audited where the business requires it,** with an audit extension of the database in shared environments; the local environment does not need it.

### Security tests

In addition to §11, integration tests check:

- the API roles have no usage on any model schema and no privilege on any object;
- no model schema is exposed through the API configuration;
- Row-Level Security is enabled and forced on every table, and every allowed role and command has a policy;
- no privilege is granted to `PUBLIC` or to a login role directly; no role except the owner has delete, truncate, references, trigger or create rights;
- the reader cannot read personal columns, cannot write and runs read-only transactions;
- a domain writer cannot write tables of another domain and cannot update a version except by closing it;
- every view runs with the caller's rights; every function has an empty search path; no function runs with its owner's rights unless it is listed as an approved administrative operation;
- column privileges and masked views match the column register;
- every login role has a statement timeout and a connection limit.

---

## 10. Migrations

1. `MIG-01` **One concern per migration.** Infrastructure, metadata, reference data, each domain and security are separate migrations, in the order of their dependencies.
2. `MIG-02` **Reference data is part of the migrations,** not of the test data: the model cannot exist without it, and it is the same in every environment. Regularly loaded reference data (exchange rates) is the only exception; it is loaded like business data (§9).
3. `MIG-03` **Released migrations are immutable.** As long as a migration has not reached the main branch, it may change freely, and the database is rebuilt. After a migration is on the main branch, every change is a new migration.
4. `MIG-04` **Every object name is fully qualified.** Nothing relies on the search path.
5. `MIG-05` **Every migration is verified** by a full rebuild of the local database, the configuration step for login roles (`SEC-20`), the database linter and the Supabase advisors (`SEC-14`), and the integration tests.

---

## 11. Test data and tests

1. `TST-01` **Test data is synthetic and deterministic.** A generator creates it with a fixed random seed and a configurable volume. It never contains real personal data, and generated rows are recognizable as such.
2. `TST-02` **Test data obeys every rule of the model.** Histories without overlap (written as a seed load with past lower bounds, §5), immutable events, complete snapshots that reconcile with the events. The database constraints check this while the data is loaded; a generator error fails the load.
3. `TST-03` **Every rule about the database has a test.** For each such rule, an integration test checks it against the live database: every table is registered, classified, described, mapped to BIAN/FIBO and protected; every class follows its rules; every invariant holds. Rules about the working process (for example how a FIBO concept is found) are checked in the review of the entity list (§12). *Reason:* rules without tests are not followed by the next migration.
4. `TST-04` **Tests show that wrong data is rejected,** not only that correct data is accepted: an overlapping version, a changed event, a wrong currency, a write by the reading role must all fail.
5. `TST-05` **Tests never change shared data.** Each test runs in a transaction that is rolled back; checks deferred to commit are tested by switching them to immediate inside that transaction.

---

## 12. Working process

`PRO-01` Claude works through these phases in order. Each phase ends with a check; the next phase starts only when the check passes:

| Phase | Content | Check |
|---|---|---|
| 1. Scope | Business domains and reference data from §3, adjusted with the user; BIAN service domains and FIBO modules that cover them; current releases of both | The user confirms the scope |
| 2. Entity list | One row per planned table: domain, class (§4), BIAN service domain, FIBO concept with verified identifier, business key, main attributes, references, deviations with reasons, invariants across rows; the number of tables per area compared with the guide values in §3; the project decisions on the MAY rules, or the confirmation of their defaults (`PRO-04`) | The user approves the list |
| 3. Foundation | Schemas, metadata structures, security defaults, reference data | Database rebuild, linter, tests |
| 4. Domains | One domain at a time, each complete in its migration (§6) | Database rebuild, linter, tests |
| 5. Roles | Application roles, grants and policies | Security tests |
| 6. Tests | Tests for every rule about the database (`TST-03`), first against the empty model | All tests green |
| 7. Test data | Synthetic generator; invariant and reconciliation tests on the loaded data | Rebuild with data succeeds, all tests green |
| 8. Documentation | Generated schema documentation; data-model rules in `CLAUDE.md` | Documentation test green |
| 9. Release | Changes reach the main branch according to the project's workflow (for example a pull request or a direct commit) | The project's checks are green, including the integration tests on the local database (`MIG-05`); a review where the workflow has one |

Rules:

1. `PRO-02` **Changes after the release.** After the release, the migrations are fixed. Every later change goes through the same phases, starting with an updated entity list.
2. `PRO-03` **Version of this guideline.** The project records the version of this document that it follows in the standard versions register (§8). When it adopts a newer version, it checks the rules that the change log names against the model and records the result in the entity list.
3. `PRO-04` **Defaults of the MAY decisions.** Until the project records its own decision, the default of each MAY decision applies (see "Rules at a glance"). A decision that differs from the default is recorded in the entity list and in `CLAUDE.md`; it is not a deviation, because the rule allows the choice.

---

## Change log

The version of this document follows semantic versioning:

| Part | Raised when | Effect on an existing model |
|---|---|---|
| MAJOR | a MUST or SHOULD rule is added or made stricter | the model may no longer comply; the rules named in the change log are checked (`PRO-03`) |
| MINOR | a MAY rule or other content is added, or a rule is relaxed or removed | a compliant model stays compliant |
| PATCH | wording, examples or references are corrected without changing the meaning of a rule | none |

- Every released change raises the version and adds a row to the table below. A change is released when it reaches the main branch or is copied into a project; until then, changes belong to the next version.
- Each row names the IDs of the rules that were added, changed or removed (see "Rule IDs"). The ID of a removed rule is never used again.
- The contents list at the start is updated whenever a heading changes.

| Version | Date | Changes |
|---|---|---|
| 1.0.0 | 2026-11-08 | First version |
