"""Les routes d'une application, énumérées pour les tests de « fermé par défaut » (spec § 3.10).

FastAPI garde un routeur inclus comme un seul élément de `app.routes` : on le déplie avec
`iter_route_contexts`, qui rend chaque route avec son chemin complet et les dépendances du routeur.
"""

from fastapi import FastAPI
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts


def routes_de_l_api(app: FastAPI) -> list[RouteContext]:
    """Les routes écrites par nous (`APIRoute`), préfixes et dépendances de routeur compris."""
    return [c for c in iter_route_contexts(app.router.routes) if isinstance(c.original_route, APIRoute)]


def autres_routes(app: FastAPI) -> list[RouteContext]:
    """Tout ce qui n'est pas une `APIRoute` : ces routes échappent aux dépendances, il faut les connaître."""
    return [c for c in iter_route_contexts(app.router.routes) if not isinstance(c.original_route, APIRoute)]
