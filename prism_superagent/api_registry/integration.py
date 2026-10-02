"""Narrow adapter between Phase 2 deterministic routing and the API registry."""


def classify_chat_routes(content, deterministic_engine, api_registry, web_mode=False):
    graph = deterministic_engine.classify(content, web_mode=web_mode)
    if graph is not None and graph.kind == "unit_conversion":
        from prism_superagent.engine.math_tools import execute_math

        try:
            execute_math("unit_conversion", graph.nodes[0].inputs)
        except ValueError:
            # Currency pairs look syntactically like units to the Phase 2 parser;
            # let the specialized currency capability handle unsupported units.
            api_match = api_registry.match(content)
            if api_match:
                return None, api_match
    if graph is None:
        return None, api_registry.match(content)
    return graph, None


def select_chat_provider(deterministic_graph, api_match, selected_provider):
    if deterministic_graph is not None:
        return "deterministic"
    if api_match is not None:
        return "api_registry"
    return selected_provider
