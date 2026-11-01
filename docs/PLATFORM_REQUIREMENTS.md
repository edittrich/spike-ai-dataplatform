# Prompt 1: Functional Requirements and Roadmap

> Run this after Prompt 0, in the `spike-ai-dataplatform-steps` repository. Copy
> everything below the line.

---

You are helping me rebuild a project from scratch, step by step. This is step 1.
This prompt defines WHAT the product must do. It deliberately says nothing about
HOW.

Your task now: write docs/REQUIREMENTS.md and docs/ROADMAP.md, as specified at the
end of this brief. Do not choose technologies, propose an architecture, or write
code. Do not name any database, framework, or vendor. Deliver both documents in
one pull request, following CLAUDE.md, then stop so I can review them. Do not merge
it yourself.

## Product

An AI-enabled financial data platform, built as a proof of concept on synthetic
data. It gives analysts, risk and compliance staff, data stewards, and AI agents
one trustworthy, governed way to find, understand, and question a retail and
corporate bank's data, in plain English or through precise queries.

## Business domains

Aligned with the BIAN and FIBO industry standards:

- Party & Customer: individuals, organizations, addresses, identification
  documents, customer roles, KYC status, AML risk rating.
- Deposit & Liquidity: accounts, balances, transactions, interest terms, overdraft
  facilities.
- Loan & Credit Risk: applications, agreements, disbursements, repayment schedules,
  collateral, non-performing loans.
- Shared reference data: countries (including AML high-risk flags), currencies,
  NACE industry classifications (including risk levels).

Every business record keeps its full history, so users can see what is true now
and what was true at an earlier point in time.

## Capabilities

1. **Reproducible data.** Generate a realistic, deterministic synthetic dataset of
   about 1,000 parties (80% individuals, 20% organizations) with deposits, loans,
   and history. No real customer data is ever used.

2. **Governed metrics.** Provide one agreed definition per business metric, such as
   available balance, total principal exposure, average loan amount, average
   interest rate, NPL count, and NPL ratio. Metrics can be sliced by country,
   industry, currency, customer segment, and AML risk. A combined Customer 360 view
   spans customer, deposit, and loan data.

3. **Relationship exploration.** Answer multi-hop questions that are awkward as
   tables, for example: from an overdrawn account to its customer, the master
   party, their loans, and the pledged collateral.

4. **Business concepts.** Model the domain vocabulary and ground it in FIBO. A user
   can move from a concept, to its narrower concepts, to the data that implements
   it, to the metrics built on it, to the live records.

5. **Data catalog and governance.** Users can search for any dataset or column and
   see its description, owner, domain, PII classification, profile statistics, and
   business-concept mapping. Each domain publishes a data contract with its schema,
   allowed values, and SLAs (freshness, availability, retention, quality score).
   SLAs are measured and reported, not only declared. Automated quality checks
   report a scorecard. Lineage shows how data flows from source to metric, down to
   column level.

6. **Natural-language answers.** A user asks a question in English. The platform
   combines semantic search, governed metrics, relationships, database records, and
   business concepts into one answer, and shows the evidence from each source. If
   one source fails, the answer still arrives, with that source marked unavailable.

7. **Access for AI agents.** All of the above is available as a standard set of
   tools that any compliant agent can call: catalog search, metrics, graph
   traversal, concept lookup, read-only database queries, quality checks, and the
   combined answer. An agent can solve a multi-step question on its own. The LLM
   provider is switchable by one setting, with a free local option. An invalid or
   incomplete setting must refuse to start, never silently use a different provider.

8. **Safety and access control.**
   - AI-facing access is strictly read-only. Write and side-effect attempts are
     rejected, including disguised ones.
   - Personal data is redacted by field meaning in everything returned to an AI,
     even when a query renames a column or returns a whole object.
   - Special-category PII (date of birth, gender, ID and registration numbers) is
     never exposed through metrics.
   - Standard users cannot see AML risk classifications through any path, including
     combined views. Privileged users can.
   - All retrieved content is treated as untrusted. Prompt-injection attempts are
     quarantined, not merely flagged, on every tool result.
   - Every entry point requires authentication and fails closed if unconfigured.
   - Each agent has its own credentials. Every AI tool call is written to an
     append-only audit log with caller, tool, redacted arguments, row count,
     outcome, and trace ID, so "who queried this customer?" can be answered.
   - No component keeps a vendor default password.
   - Error messages never leak internals.

9. **Interactive explorer.** A web interface where a person can ask questions and
   inspect the answer, the evidence from each source, and timing. It requires
   authentication.

10. **Observability.** Every AI tool call and retrieval step is measured and traced:
    latency, success or failure, token usage. Operators see platform health on
    dashboards and receive alerts on real failure conditions. Every alert is proven
    to fire at least once.

11. **Evaluation.** A repeatable benchmark scores retrieval and answer quality using
    context relevance, groundedness, and answer relevance. It must be able to fail,
    must disclose when scores are non-deterministic, and scores from different judge
    models must never be presented as comparable. Benchmark questions include:
    - "Identify overdrawn deposit account customer risk exposure and master party
      entities"
    - "Query total available balance deposit liquidity metric from semantic layer"
    - "Traverse credit risk and loan agreement pledged collateral assets in
      knowledge graph"
    - "Check data quality assertions and SLA scorecard for table deposit_account"
    - "Search data catalog for table party_individual and column metadata"

12. **Operability.** One command takes an empty checkout to a fully loaded platform.
    The load is repeatable, retries failures, and keeps a run history. Expiring
    credentials are renewed automatically. Backups run on a schedule, and a restore
    has been executed and timed.

## Cross-cutting rules

- Consistency: the same question must give the same number from every source.
  Counts include only current records unless history is requested.
- Honesty: a test, benchmark, or agent run reports its real outcome, never an
  unconditional pass.
- Secrets are never stored in the code or history.

## Out of scope

Real customer data, real payment or banking transactions, end-user self-signup,
agents that write data, and multi-region or production-grade high availability.

## Documents to write

docs/REQUIREMENTS.md contains, in this order:

1. The goal: the question this spike must answer, and the criteria that end it.
2. Measurable targets for answer latency, retrieval quality, cost per answer,
   recovery time, and what must run on one local workstation. Mark each value as a
   proposal until I confirm it.
3. Numbered, testable requirements grouped by capability.
4. A list of open questions.

docs/ROADMAP.md is an ordered list of steps, each with a small, testable outcome and
no technology names. Step 2 is the data foundation. The next step carries one
question end to end, from data to answer, including access control, redaction,
tracing, and a benchmark check. Broaden capabilities only after that.
