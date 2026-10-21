# MCP status

Version 2 intentionally has no MCP runtime. The analyst and optional critic have
no tools. Python selects inputs and owns all persistence and graph mutations.

Add an MCP integration only when a validated use case needs a distinct external
capability and its approval, data-flow, and evaluation boundaries are implemented
in code. A manifest alone is not treated as an enforced security boundary.
