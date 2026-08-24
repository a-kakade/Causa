# Causa — Olist Data Foundation

Causa is a KPI Decision Intelligence project. This milestone does **not** touch agents,
backend architecture, frontend, RAG, PostgreSQL, or LLM workflows. The sole objective
right now is to understand and validate the [Olist Brazilian E-Commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
thoroughly enough to design the correct Causa data model and KPI layer afterward.

## Scope of this milestone

- Load and inspect every Olist CSV table.
- Profile schema, types, null rates, cardinality, and referential integrity across tables.
- Document findings in `docs/` (data dictionary, data quality report, proposed data model).
- No application code, no database, no agents — just data understanding.

## Repository structure

```
causa/
├── README.md
├── data/
│   └── raw/
│       └── olist/            # place the raw Olist CSVs here (not committed)
├── notebooks/
│   └── 01_olist_eda.ipynb    # exploratory data analysis
├── scripts/
│   └── profile_olist.py      # automated profiling script (schema, nulls, keys, joins)
├── docs/
│   ├── DATA_DICTIONARY.md    # table-by-table, column-by-column reference
│   ├── DATA_QUALITY_REPORT.md# findings from profiling: nulls, duplicates, orphans, outliers
│   └── DATA_MODEL.md         # proposed entity relationships for the Causa data model
└── requirements.txt
```

## Getting the data

1. Download the Olist dataset from Kaggle: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
2. Extract the CSV files into `data/raw/olist/`. Expected files:
   - `olist_customers_dataset.csv`
   - `olist_orders_dataset.csv`
   - `olist_order_items_dataset.csv`
   - `olist_order_payments_dataset.csv`
   - `olist_order_reviews_dataset.csv`
   - `olist_products_dataset.csv`
   - `olist_sellers_dataset.csv`
   - `olist_geolocation_dataset.csv`
   - `product_category_name_translation.csv`

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

## Usage

Run the profiling script to generate a schema/quality summary:

```bash
python scripts/profile_olist.py
```

Then explore interactively in `notebooks/01_olist_eda.ipynb`.

## Deliverables

- [ ] `docs/DATA_DICTIONARY.md` — every table and column, defined
- [ ] `docs/DATA_QUALITY_REPORT.md` — nulls, duplicates, orphan keys, outliers, date ranges
- [ ] `docs/DATA_MODEL.md` — proposed entity relationships and grain for each table, feeding the future Causa data model and KPI layer
