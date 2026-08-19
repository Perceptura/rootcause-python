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

## Structured queries

Concepts go by name or id. Operators are `eq neq gt gte lt lte between in contains` or their symbol spellings:

```python
>>> result = onto.query(
...     select=["Revenue", "Leads"],
...     where=[("Revenue", ">=", 300)],
...     order_by="-Revenue",
...     limit=1000,
... )
>>> result
OntologyQueryResult(rows=134)
>>> result.to_frame().head()
   marketing_spend  seasonality  leads  revenue
0            72.55        1.498  237.2    542.6
1            74.30        0.433  234.9    540.7
2            66.03        2.537  238.2    537.4
3            65.08        1.085  218.8    505.5
4            64.99        0.637  210.6    492.2
```

`to_frame()` pages through the full result transparently. The engine compiles the query into a dataset (joins, filters, aggregations across every mapped source), executes it, and returns rows along with everything it decided:

```python
>>> result.warnings      # e.g. a join over a low-cardinality key
[]
>>> result.dataset       # the compiled dataset definition, persistable via the API
```

Aggregations and grouping follow the same shape:

```python
>>> onto.query(
...     select=["customer", "Revenue"],
...     group_by=["customer"],
...     aggregate={"Revenue": "sum"},
...     order_by="-Revenue",
... ).to_frame()
```

## Natural language

`ask` translates a question into a structured query server side, runs it, and hands back both:

```python
>>> result = onto.ask("average revenue per customer in Florida last quarter")
>>> result.query         # the structured query the translator produced
>>> result.to_frame()
```

The translated query coming back with the rows means an analyst can inspect exactly what was asked, adjust it, and re-run it structurally.

## Over the REST API

Both forms are one endpoint, `POST /api/v1/workspaces/{wsId}/ontology/query`:

```bash
curl -X POST "https://sandbox.rootcause.ai/api/v1/workspaces/ws_123/ontology/query" \
  -H "Authorization: Bearer pk_your_key" \
  -H "Content-Type: application/json" \
  -d '{"query": {"conceptIds": ["c_rev"], "limit": 100}, "limit": 100}'
```

Pass `{"prompt": "..."}` instead of `query` for natural language. The response carries `rows`, `nextStartKey` for paging, `schema`, `rowCount`, the compiled `dataView`, and `warnings`. Requires the `ontology:read` scope.

## Next steps

* [Working with Digital Twins](sdk-working-with-twins.md)
* [Python API Reference](sdk-api-reference.md)
* [REST API Reference](../api-and-integrations/rest-api-reference/)
