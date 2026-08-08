#!/usr/bin/env python3
"""
===============================================================================
FIBO W3C Class URI Semantic Grounding Automation Script
===============================================================================
Explicitly links OpenMetadata catalog entities to official W3C FIBO
(Financial Industry Business Ontology) class URIs.

Actions:
1. Creates `FIBO_Ontology` Tag Classification in OpenMetadata Catalog.
2. Ingests official FIBO URIs (e.g. https://spec.edmcouncil.org/fibo/ontology/...) as tags.
3. Maps each PostgreSQL table & Cube.js semantic cube entity to its exact FIBO URI.
4. Appends FIBO W3C Semantic Grounding metadata blocks to table entity descriptions.
===============================================================================
"""

import sys
import os

# scripts/ has no __init__.py (namespace package); make it importable regardless
# of the working directory this script is launched from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts._dotenv_boot import load_env  # noqa: E402

load_env()

# _openmetadata_client reads OPENMETADATA_URL/JWT_TOKEN at import time, so it
# must be imported after load_env() -- see its module docstring.
from scripts._openmetadata_client import api_get, api_put, api_post  # noqa: E402

# FIBO Class URI Grounding Specification Map
#
# D5 (hardening plan) verification, 2026-08-08 (two passes): this map's
# URIs had never been checked against the real, upstream FIBO ontology
# source (github.com/edmcouncil/fibo) before this finding -- only
# reconciled against ontology/financial_platform_ontology.ttl's own
# (equally unverified) opinion. With live web access available, **all 19
# entries below have now been individually re-verified** by fetching the
# actual FIBO RDF/XML source files (via WebFetch and `gh api search/code`
# to locate the real defining file per concept) and confirming/refuting
# each URI against a real `owl:Class` declaration -- not inferred from
# documentation or the plausible-looking shape of a path. **15 of the 19
# were wrong and are now corrected** (each with its own comment explaining
# what the live fetch found); 4 (`Person`, `PhysicalAddress`, `Collateral`,
# `Currency`) were confirmed correct as-is. Three systematic patterns
# emerged across the corrections, worth knowing if this map is ever
# extended to a new table:
#   1. Several of FIBO's foundational concepts (Party, Organization/
#      LegalEntity, Identifier, Country) are not actually defined under
#      FIBO's own spec.edmcouncil.org/fibo/ontology/ namespace -- they're
#      imported from a separate OMG "Commons" ontology suite
#      (omg.org/spec/Commons/...) that FIBO's own files extend but don't
#      restate. A URI built by guessing "<file's own path>/<ClassName>"
#      looks plausible but doesn't resolve to where the class is actually
#      asserted for these.
#   2. Several previously-mapped paths funneled everything loan-related
#      through the generic FBC/ProductsAndServices/FinancialProductsAndServices
#      module, which is real (confirmed by listing every class it actually
#      defines -- none of them loan/deposit/credit-facility/disbursement
#      related) but doesn't contain Loan/LoanApplication/DepositAccount/
#      Balance/CreditFacility -- FIBO has a dedicated top-level LOAN domain
#      and a FBC/ProductsAndServices/ClientsAndAccounts module the original
#      mapping never referenced at all.
#   3. Two concepts this platform names (`CreditApplication` for
#      loan_application, `Disbursement` for loan_disbursement,
#      `IndustrySector` for ref_nace_industry) have **no class of that
#      exact name anywhere in FIBO** -- confirmed by enumerating every
#      class in every file a targeted search surfaced, not just failing to
#      find one occurrence. Each is mapped instead to the closest real,
#      fully-defined FIBO class for the same concept (`LoanApplication`,
#      `Payment`, `IndustrySectorClassifier` respectively), with the tag
#      renamed to match and a comment explaining the substitution.
FIBO_GROUNDING_MAP = {
    # Party & Customer Domain
    "financial.party": {
        "tag": "Party",
        # D5 (hardening plan), verified live 2026-08-08 against
        # github.com/edmcouncil/fibo's actual raw RDF/XML source (not
        # inferred from documentation): FIBO's own
        # FND/Parties/Parties.rdf references "Party" via the
        # fibo-fnd-pty-pty: prefix, but does NOT define the class there --
        # it imports and extends it (adds hasMailingAddress/hasAddress
        # restrictions, a disjointness axiom with Role) from a separate
        # OMG "Commons" ontology suite. The class's real, defining URI is
        # in that Commons namespace, not under spec.edmcouncil.org/fibo/
        # ontology/ at all -- the previous "FND/Parties/Parties/Party"
        # value looked plausible (it's the URI you'd guess from the file's
        # own path) but does not resolve to where the class is actually
        # asserted with `owl:Class`.
        "fibo_uri": "https://www.omg.org/spec/Commons/PartiesAndSituations/Party",
        "fibo_label": "cmns-pts:Party",
        "description": "An agent that is an individual or organization, capable of entering into agreements or obligations."
    },
    "financial.party_individual": {
        "tag": "Person",
        # D5: verified live 2026-08-08 -- confirmed correct as-is. Unlike
        # Party above, FND/AgentsAndPeople/People.rdf genuinely defines
        # "Person" itself (rdf:about="&fibo-fnd-aap-ppl;Person", with real
        # cardinality restrictions on date of birth/place of birth/gender),
        # at exactly this URI.
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FND/AgentsAndPeople/People/Person",
        "fibo_label": "fibo-fnd-aap-ppl:Person",
        "description": "A natural person, human individual."
    },
    "financial.party_organization": {
        "tag": "Organization",
        # D5: verified live 2026-08-08, same pattern as Party above --
        # BE/LegalEntities/LegalPersons.rdf references "LegalEntity" via
        # the cmns-org: prefix and adds one restriction
        # (isOrganizedIn exactly one Jurisdiction), but the class itself is
        # defined in the same OMG Commons namespace as Party, not under
        # FIBO's own ontology/ path. The previous
        # "FBC/FunctionalMetadata/Organizations/LegalEntity" value doesn't
        # correspond to a real file in the FIBO repository at all (a live
        # fetch 404s) -- ontology/financial_platform_ontology.ttl's
        # fibo-org: prefix declaration has the identical wrong path and is
        # corrected alongside this.
        "fibo_uri": "https://www.omg.org/spec/Commons/Organizations/LegalEntity",
        "fibo_label": "cmns-org:LegalEntity",
        "description": "A legal entity or social structure formed by people with a shared purpose."
    },
    "financial.party_role_customer": {
        "tag": "Customer",
        # D5: verified live 2026-08-08 -- there is no class named "Customer"
        # in FND/Parties/Roles.rdf (that file doesn't exist -- FND/Parties/
        # Parties.rdf is the only Parties-domain file with role content, and
        # it doesn't define Customer either). The real, fully-defined
        # "Customer" class ("a party that receives or consumes products...
        # and has the ability to choose between different products and
        # suppliers", subclass of Buyer) lives in
        # FND/ProductsAndServices/ProductsAndServices.rdf instead.
        # ontology/financial_platform_ontology.ttl's fin:Customer also
        # grounds to bian:CustomerRole -- both are legitimately correct
        # (Customer is a first-class BIAN business role concept as well as
        # a FIBO party-role concept), and the TTL references both rather
        # than this map and the TTL silently disagreeing. This map stays
        # FIBO-only since it's specifically the FIBO grounding pass (see
        # scripts/register_openmetadata_data_contracts.py for the BIAN
        # domain/product registration).
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FND/ProductsAndServices/ProductsAndServices/Customer",
        "fibo_label": "fibo-fnd-pas-pas:Customer",
        "description": "A party in the role of purchasing or receiving financial products or services."
    },
    "financial.party_address": {
        "tag": "PhysicalAddress",
        # D5: verified live 2026-08-08 -- confirmed correct as-is.
        # FND/Places/Addresses.rdf genuinely defines "PhysicalAddress"
        # itself (subclass of Address, with real restrictions on postcode/
        # country/municipality/city name/subdivisions) at exactly this URI.
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FND/Places/Addresses/PhysicalAddress",
        "fibo_label": "fibo-fnd-plc-adr:PhysicalAddress",
        "description": "A physical location address where a party resides or conducts business."
    },
    "financial.party_identification": {
        "tag": "Identifier",
        # D5: verified live 2026-08-08, same OMG Commons pattern as Party/
        # LegalEntity/Country -- FND/Arrangements/IdentifiersAndIndices.rdf
        # only defines ReassignableIdentifier as a subclass of
        # cmns-id:Identifier; the base "Identifier" class itself is defined
        # in the separate OMG Commons Identifiers ontology, not under
        # FIBO's own ontology/ path as previously mapped.
        "fibo_uri": "https://www.omg.org/spec/Commons/Identifiers/Identifier",
        "fibo_label": "cmns-id:Identifier",
        "description": "Official government passport, national ID, or tax identification reference."
    },

    # Deposit Domain
    "financial.deposit_account": {
        "tag": "DepositAccount",
        # D5: verified live 2026-08-08 -- DepositAccount is genuinely
        # defined in FBC/ProductsAndServices/ClientsAndAccounts.rdf
        # ("provides a record of money placed with a depository institution
        # for safekeeping and management"), not under
        # .../FinancialProductsAndServices/ as previously mapped -- that
        # module exists and is real, but doesn't contain this class.
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FBC/ProductsAndServices/ClientsAndAccounts/DepositAccount",
        "fibo_label": "fibo-fbc-pas-caa:DepositAccount",
        "description": "A financial account held at a bank or institution allowing funds to be deposited and withdrawn."
    },
    "financial.deposit_balance": {
        "tag": "AccountBalance",
        # D5: verified live 2026-08-08 -- FBC/FinancialInstruments/
        # FinancialInstruments.rdf defines 25 classes, none named "Balance"
        # (it's about securities/derivatives, not accounts). The real class
        # ("amount of money available or owed... the net amount after
        # factoring in all debits and credits", subclass of MonetaryAmount)
        # is genuinely defined in FBC/ProductsAndServices/
        # ClientsAndAccounts.rdf instead -- the same module DepositAccount
        # was corrected to above.
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FBC/ProductsAndServices/ClientsAndAccounts/Balance",
        "fibo_label": "fibo-fbc-pas-caa:Balance",
        "description": "Real-time ledger position balance and available funds."
    },
    "financial.deposit_transaction": {
        "tag": "AccountingTransaction",
        # D5: verified live 2026-08-08 -- there is no class simply named
        # "Transaction" defined in FBC/ProductsAndServices/
        # FinancialProductsAndServices.rdf (enumerated all 51 classes it
        # defines: trade/contract/product lifecycles, brokers, baskets --
        # none are transaction-ledger concepts). The real, fully-defined,
        # and more precisely matching class is "AccountingTransaction"
        # ("event recognized by an entry in the records of an account") in
        # FBC/ProductsAndServices/ClientsAndAccounts.rdf -- tag renamed to
        # match.
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FBC/ProductsAndServices/ClientsAndAccounts/AccountingTransaction",
        "fibo_label": "fibo-fbc-pas-caa:AccountingTransaction",
        "description": "An event involving transfer of monetary value between accounts."
    },
    "financial.deposit_interest_term": {
        "tag": "InterestRateTerm",
        # D5: verified live 2026-08-08 -- "InterestRate" is genuinely
        # defined in FND/Accounting/CurrencyAmount.rdf ("amount charged,
        # expressed as a percentage of principal, in exchange for the use
        # of assets", subclass of PercentageMonetaryAmount), not under
        # FBC/DebtAndEquities/Debt/ as previously mapped.
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FND/Accounting/CurrencyAmount/InterestRate",
        "fibo_label": "fibo-fnd-acc-cur:InterestRate",
        "description": "Contractual rate and calculation terms for interest accrual."
    },
    "financial.deposit_overdraft_facility": {
        "tag": "CreditFacility",
        # D5: verified live 2026-08-08 -- "CreditFacility" is genuinely
        # defined in FBC/DebtAndEquities/Debt.rdf ("credit agreement that
        # allows the borrower to periodically take out money over an
        # extended period of time"), not under FBC/ProductsAndServices/
        # FinancialProductsAndServices/ as previously mapped -- same
        # generic-module-doesn't-actually-contain-this-class pattern as
        # DepositAccount/Balance/Loan/LoanApplication above.
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FBC/DebtAndEquities/Debt/CreditFacility",
        "fibo_label": "fibo-fbc-dae-dbt:CreditFacility",
        "description": "An agreement permitting account balance to drop below zero up to a limit."
    },

    # Loan Domain
    "financial.loan_application": {
        # D5: verified live 2026-08-08 -- there is no class named
        # "CreditApplication" anywhere in the FIBO repository. The real,
        # fully-defined class for exactly this concept ("request by a
        # potential borrower to a potential lender to borrow money... used
        # to decide whether to grant the loan") is "LoanApplication",
        # living in FIBO's dedicated LOAN domain
        # (LOAN/LoansGeneral/LoanApplications.rdf) -- a domain the previous
        # mapping never referenced at all, routing every loan-related
        # concept through the generic FBC/ProductsAndServices module
        # instead. Tag corrected to match the real class name.
        "tag": "LoanApplication",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/LOAN/LoansGeneral/LoanApplications/LoanApplication",
        "fibo_label": "fibo-loan-ln:LoanApplication",
        "description": "A formal application submitted by a customer for a credit line or loan."
    },
    "financial.loan_agreement": {
        # D5: verified live 2026-08-08 -- "Loan" is genuinely defined in
        # FIBO's LOAN/LoansGeneral/Loans.rdf (subclassing
        # CreditAgreementRepaidPeriodically/DebtInstrument from imported
        # ontologies), not under FBC/ProductsAndServices/
        # FinancialProductsAndServices/ as previously mapped -- same
        # never-used-the-real-LOAN-domain pattern as loan_application above.
        "tag": "Loan",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/LOAN/LoansGeneral/Loans/Loan",
        "fibo_label": "fibo-loan-ln:Loan",
        "description": "A binding contract under which a lender advances funds to a borrower."
    },
    "financial.loan_repayment_schedule": {
        "tag": "PaymentSchedule",
        # D5: verified live 2026-08-08 -- PaymentSchedule is genuinely
        # defined in FND/ProductsAndServices/PaymentsAndSchedules.rdf
        # (subclasses Schedule, has Payment members), not under
        # FBC/DebtAndEquities/Debt/ as previously mapped.
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FND/ProductsAndServices/PaymentsAndSchedules/PaymentSchedule",
        "fibo_label": "fibo-fnd-pas-ps:PaymentSchedule",
        "description": "Amortization schedule detailing periodic principal and interest payment installments."
    },
    "financial.loan_disbursement": {
        # D5: verified live 2026-08-08 -- there is no class named
        # "Disbursement" anywhere in FIBO. Checked every plausible location:
        # LOAN/LoansGeneral/LoanEvents.rdf defines 8 loan-lifecycle event
        # classes (CollateralValuation, Prepayment, RepaymentPhase, ...)
        # but no Disbursement -- only a `hasDisbursementDate` property on
        # Loan; FBC/ProductsAndServices/FinancialProductsAndServices.rdf's
        # full 51-class list has none either. The closest real, fully-
        # defined FIBO class for "money transferred in fulfillment of an
        # obligation" is the generic "Payment"
        # (FND/ProductsAndServices/PaymentsAndSchedules.rdf, the same file
        # PaymentSchedule was corrected to above) -- not disbursement-
        # specific, but a real class rather than an invented one. Tag
        # renamed to match; description kept disbursement-specific since
        # that's still an accurate description of what this table holds.
        "tag": "Payment",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FND/ProductsAndServices/PaymentsAndSchedules/Payment",
        "fibo_label": "fibo-fnd-pas-psch:Payment",
        "description": "Execution payment transferring approved loan principal to borrower target account."
    },
    "financial.loan_collateral": {
        "tag": "CollateralAsset",
        # D5: verified live 2026-08-08 -- confirmed correct as-is.
        # FBC/DebtAndEquities/Debt.rdf genuinely defines "Collateral"
        # itself ("something pledged as security to ensure fulfillment of
        # an obligation... to lend money, extend credit, or provision
        # securities", subclass of cmns-pts:Undergoer) at exactly this URI.
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FBC/DebtAndEquities/Debt/Collateral",
        "fibo_label": "fibo-fbc-dae-dbt:Collateral",
        "description": "Pledged asset or security guaranteeing loan repayment."
    },

    # Reference Data
    "ref.ref_country": {
        "tag": "Country",
        # D5: verified live 2026-08-08, same OMG Commons pattern as Party/
        # LegalEntity/Identifier -- "FND/Places/Locations/" doesn't even
        # correspond to a real file (FND/Places/ only contains Addresses.rdf/
        # Facilities.rdf/RealProperty.rdf/VirtualPlaces.rdf, confirmed via a
        # live directory listing). FND/Places/Addresses.rdf references
        # "Country" via `owl:imports` from the OMG Commons Locations
        # ontology, where the class is actually defined.
        "fibo_uri": "https://www.omg.org/spec/Commons/Locations/Country",
        "fibo_label": "cmns-loc:Country",
        "description": "ISO 3166-1 geopolitical country entity."
    },
    "ref.ref_currency": {
        "tag": "Currency",
        # D5: verified live 2026-08-08 -- confirmed correct as-is.
        # FND/Accounting/CurrencyAmount.rdf genuinely defines "Currency"
        # itself ("medium of exchange value, defined by reference to the
        # geographical location of the monetary authorities responsible for
        # it", subclass of cmns-qtu:MeasurementUnit, with hasMinorUnit/
        # hasNumericCode/hasTextualName restrictions) at exactly this URI.
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FND/Accounting/CurrencyAmount/Currency",
        "fibo_label": "fibo-fnd-acc-cur:Currency",
        "description": "ISO 4217 medium of exchange currency."
    },
    "ref.ref_nace_industry": {
        # D5: verified live 2026-08-08 -- there is no class named
        # "IndustrySector" anywhere in FIBO (FND/Organizations/
        # FormalOrganizations.rdf, the previously-mapped file, defines
        # Employee/Employer/Employment/Group/Organization/Agent -- no
        # industry concept at all). The real, fully-defined, and NACE-
        # relevant class is "IndustrySectorClassifier"
        # (FND/Arrangements/ClassificationSchemes.rdf) -- "standardized
        # classification or delineation for an organization... by industry",
        # whose parent concept IndustrySectorClassificationScheme's own
        # definition explicitly names NACE as a real-world example. Tag
        # renamed to match.
        "tag": "IndustrySectorClassifier",
        "fibo_uri": "https://spec.edmcouncil.org/fibo/ontology/FND/Arrangements/ClassificationSchemes/IndustrySectorClassifier",
        "fibo_label": "fibo-fnd-arr-cls:IndustrySectorClassifier",
        "description": "NACE Rev. 2 economic activity industry classification."
    }
}

def main() -> None:
    """Creates the FIBO_Ontology tag classification and applies a FIBO URI
    tag to each table entity named in FIBO_GROUNDING_MAP above, grounding the
    catalog's BIAN/FIBO-aligned tables to their real FIBO ontology class."""
    print("🌐 Executing FIBO W3C Class URI Semantic Grounding across Catalog Entities...")

    # 1. Create Classification `FIBO_Ontology`
    print("🏷️ Creating Tag Classification `FIBO_Ontology`...")
    api_put("classifications", {
        "name": "FIBO_Ontology",
        "displayName": "W3C FIBO Ontology",
        "description": "Financial Industry Business Ontology (FIBO) W3C Class URIs published by EDM Council."
    })

    # 2. Register FIBO Tags
    for key, info in FIBO_GROUNDING_MAP.items():
        tag_payload = {
            "name": info["tag"],
            "displayName": info["fibo_label"],
            "description": f"FIBO Class URI: {info['fibo_uri']}\n\n{info['description']}",
            "classification": "FIBO_Ontology"
        }
        api_put("tags", tag_payload)

    # 3. Fetch Catalog Tables and Apply Grounding Tags & Descriptions
    tables_resp = api_get("tables?fields=columns,tags&limit=100")
    if not tables_resp or "data" not in tables_resp:
        print("❌ Could not fetch tables from catalog!")
        return

    grounded_count = 0
    for tbl in tables_resp["data"]:
        schema_name = tbl["databaseSchema"]["name"]
        tbl_name = tbl["name"]
        key = f"{schema_name}.{tbl_name}"

        if key in FIBO_GROUNDING_MAP:
            info = FIBO_GROUNDING_MAP[key]
            tag_fqn = f"FIBO_Ontology.{info['tag']}"
            
            existing_tags = tbl.get("tags", [])
            tag_names = [t.get("tagFQN") for t in existing_tags]
            
            if tag_fqn not in tag_names:
                existing_tags.append({
                    "tagFQN": tag_fqn,
                    "labelType": "Automated",
                    "state": "Confirmed",
                    "source": "Classification"
                })

            base_desc = tbl.get("description", "").split("\n\n---\n#### 🌐 W3C FIBO Semantic Grounding")[0]
            fibo_grounding_block = f"{base_desc}\n\n---\n#### 🌐 W3C FIBO Semantic Grounding\n- **FIBO W3C Class URI:** [`{info['fibo_uri']}`]({info['fibo_uri']})\n- **FIBO Ontology Prefix:** `{info['fibo_label']}`\n- **Ontology Definition:** {info['description']}"

            put_payload = {
                "name": tbl["name"],
                "displayName": tbl.get("displayName", tbl["name"]),
                "description": fibo_grounding_block,
                "databaseSchema": tbl["databaseSchema"]["fullyQualifiedName"],
                "columns": tbl.get("columns", []),
                "tags": existing_tags,
                "tableType": tbl.get("tableType", "Regular")
            }
            res = api_put("tables", put_payload)
            if res:
                grounded_count += 1
                print(f"  🌐 Grounded `{key}` ➔ FIBO URI: {info['fibo_uri']}")

    # Refresh Search Indexes
    api_post("apps/trigger/SearchIndexingApplication")
    print(f"\n✅ Successfully Grounded {grounded_count} Catalog Table Entities to Official W3C FIBO Class URIs!")

if __name__ == "__main__":
    main()
