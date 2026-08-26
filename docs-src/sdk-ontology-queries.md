# Ontology Queries

The ontology is the workspace's semantic layer: concepts are the shared meaning of columns across sources, and the query engine joins, filters, and aggregates through them so you never hand-write reconciliation SQL. This guide queries it from Python; outputs shown are real transcripts.

## Concepts

Every upload gets concepts during ingest. List them, or grab one by name with tab completion:

```python
>>> ws = rc.workspace("Customer Analytics")
>>> onto = ws.ontology
>>> onto.concepts
                      id             name    type classification  sources
0  5Z8yb2XPu9LwDHAUdexjv          Revenue  Number           None        1
1  AFpGasdD0EqEP0hmduLHN  Marketing Spend  Number           None        1
2  ML8Ign3fzxIFhQeyEQcwy      Seasonality  Number           None        1
3  uYGwvfVLj9ND4SCTIaAWc            Leads  Number           None        1

>>> onto["Revenue"]["id"]
'5Z8yb2XPu9LwDHAUdexjv'
```

## Anchor SQL

Queries are Anchor SQL: SQL over concepts, not tables. Reference a concept by quoted name and the ontology plans the joins across every mapped source — there is no table to `FROM` and no `JOIN` to write:

```python
>>> result = onto.sql('SELECT "Revenue", "Leads" WHERE "Revenue" >= 300 ORDER BY "Revenue" DESC')
>>> result
AnchorSqlResult(rows=134)
>>> result.to_frame().head()
   revenue  leads
0    542.6  237.2
1    540.7  234.9
2    537.4  238.2
3    505.5  218.8
4    492.2  210.6
```

`to_frame()` pages through the full result transparently (drive pages by hand with `result.next_start_key` passed back as `start_key=`). The result also carries everything the planner decided:

```python
>>> result.warnings      # e.g. a join over a low-cardinality key
[]
>>> result.plan          # scope, spine, join and grain chips, plus the join strategy
>>> result.units         # unit id per column, where the ontology knows one
```

The reserved anchors `entity`, `time` and `location` take grains, aggregates group and filter as in SQL, and metrics defined in the workspace go by name verbatim:

```python
>>> onto.sql('SELECT "customer", sum("Revenue") GROUP BY "customer" ORDER BY sum("Revenue") DESC').to_frame()
>>> onto.sql('SELECT time(month), avg("Monthly Charges") WHERE "Contract" = \'Month-to-month\' GROUP BY time(month)').to_frame()
```

`FROM` is scope sugar only — `FROM source:"shipments"` narrows which source answers, it never names a table.

## Metadata commands

`SHOW CONCEPTS`, `SHOW METRICS`, `SHOW SOURCES` and `DESCRIBE "x"` answer what there is to query, as rows:

```python
>>> onto.sql("SHOW CONCEPTS").to_frame()
>>> onto.sql('DESCRIBE "Revenue"').to_frame()
```

## When a statement is refused

A refused statement raises `AnchorSqlError` carrying the structured compile error — the machine `code`, the offending `span`, near-miss `candidates`, and a `suggested_query` when the engine has one:

```python
>>> onto.sql('SELECT "Revenu"')
AnchorSqlError: [unknown_concept] Unknown concept "Revenu". Closest matches: Revenue
Try: SELECT "Revenue"
```

## Over the REST API

The same engine is one endpoint, `POST /api/v1/workspaces/{wsId}/ontology/query`:

```bash
curl -X POST "https://sandbox.rootcause.ai/api/v1/workspaces/ws_123/ontology/query" \
  -H "Authorization: Bearer pk_your_key" \
  -H "Content-Type: application/json" \
  -d '{"anchorSql": "SELECT \"Revenue\" WHERE \"Region\" = '\''US'\''", "limit": 100}'
```

It always answers 200 with a union under `data` discriminated by `ok` and `kind`: rows responses carry `rows`, `columns`, `units`, `rowCount`, the compiled `plan`, `warnings` and `nextStartKey` (pass back as `startKey` for the next page); SHOW/DESCRIBE answer a `metadata` listing; refused statements answer `ok: false` with the structured error. Requires the `ontology:read` scope.

## Next steps

* [Working with Digital Twins](sdk-working-with-twins.md)
* [Python API Reference](sdk-api-reference.md)
* [REST API Reference](../api-and-integrations/rest-api-reference/)
