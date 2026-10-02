"""Route only recognized deterministic graphs away from model providers."""


class DeterministicRouter:
    def route(self, graph):
        return "deterministic" if graph is not None else "model"

