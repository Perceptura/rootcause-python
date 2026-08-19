# Sources from Connectors

From a warehouse table to a causal model without leaving Python: register a connector, author custom SQL against the live database, import the result as a source, and model it. Outputs shown are real transcripts against a PostgreSQL database; Snowflake, MySQL, ClickHouse, MongoDB, S3, and the other connector types follow the same verbs — swap the `type` and credentials.

## Register and test

Credentials are stored encrypted server-side and are never returned by the API — connector reads redact them.

```python
>>> ws = rc.workspace("connector-demo", create=True)
>>> connector = ws.add_connector(
...     "demo-warehouse", "PostgreSQL",
...     host="db.internal", port=5432,
...     database="warehouse", username="demo", password=os.environ["DB_PASSWORD"],
... )
>>> connector.test()
{'isConnected': True}
```

## Browse the schema

The same hierarchy the UI shows — for SQL connectors: schemas, then tables, then columns (Snowflake adds warehouses and databases above them):

```python
>>> connector.browse("tables", schema="public")
{'options': [{'value': 'store_weeks',
   'label': 'store_weeks',
   'type': None,
   'metadata': {'columnCount': '6'}}],
 'hierarchy': ['schemas', 'tables', 'columns'],
 'currentLevel': 'tables',
 'nextLevel': 'columns'}
```

## Author custom SQL against the live database

`query()` runs your SQL with a row cap and returns sample rows as a DataFrame. Nothing is stored, and database errors come back verbatim, so the authoring loop stays tight:

```python
>>> connector.query("SELECT * FROM store_week")
RootCauseError: Query preview failed: Failed to prepare query: ERROR:  relation "store_week" does not exist
LINE 1: SELECT * FROM store_week
                      ^

>>> connector.query(
...     "SELECT region, week, marketing_spend, conversions, revenue FROM store_weeks ORDER BY week",
...     limit=5,
... )
  region        week marketing_spend conversions revenue
0   amer  2024-01-01           36.12        82.2   440.2
1   emea  2024-01-01           36.30        90.9   460.4
2   apac  2024-01-01           45.56       103.6   547.5
3   emea  2024-01-08           46.72        99.3   505.0
4   amer  2024-01-08           40.68        92.0   442.0
```

## Import the query result as a source

The same SQL, minus the safety net: `import_query()` materialises the full result set as a source in the workspace and blocks until ingest completes. `import_table("store_weeks")` is the no-SQL shorthand for a whole table.

```python
>>> source = connector.import_query(
...     "SELECT region, week, marketing_spend, footfall, conversions, revenue FROM store_weeks",
...     name="store-weeks",
... )
>>> source.to_frame().head()
  region       week  marketing_spend  footfall  conversions  revenue
0   emea 2024-01-01            36.30     247.4         90.9    460.4
1   emea 2024-01-08            46.72     243.1         99.3    505.0
2   emea 2024-01-15            46.31     270.2         97.3    516.5
3   emea 2024-01-22            43.42     244.9        105.5    564.7
4   emea 2024-01-29            28.18     192.5         70.7    373.6
```

## Straight to a causal model

A source-backed twin, discovery + training in one pass, and a question:

```python
>>> twin = ws.create_twin("Store weeks", source_id=source.id)
>>> twin.run_pipeline()
Twin('Store weeks', kind=static, version=Z08TxdUFFQPTWlvNSQH2r, state=trained)

>>> twin.intervene({"marketing_spend": rc.pct(+15)}, outcomes=["revenue"]).to_frame()
          name   baseline  intervention
0  avg_revenue  517.44498    537.604876
```

The loop from here is the same as any other source: re-import or sync on a schedule, `twin.update()` to fold new rows in ([Working with Digital Twins](sdk-working-with-twins.md#keeping-a-trained-model-current)), and [Temporal and Panel Twins](sdk-temporal-and-panel-twins.md) for time series and per-environment modelling.

Over REST, the same loop is `POST /connectors` → `POST /connectors/{id}/preview-query` → `POST /connectors/{id}/import` — see the [REST API Reference](../api-and-integrations/rest-api-reference/).

## Run it yourself

{% file src="../.gitbook/assets/rootcause-sdk-connectors.ipynb" %}
Download the connectors notebook
{% endfile %}
