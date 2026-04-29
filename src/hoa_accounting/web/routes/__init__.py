"""Route Blueprints, grouped by URL prefix.

Each module in this package exposes a ``make_<area>_blueprint(ctx)``
factory that builds and returns a Flask :py:class:`~flask.Blueprint`.
``app.py`` constructs the shared :py:class:`RouteContext`, calls each
factory, and registers the resulting Blueprints.

This split is a pure mechanical refactor: route handlers are moved
verbatim, with the only changes being (a) ``@app.get/post`` →
``@bp.get/post`` and (b) closure references to ``_open_db`` / page
factories rewired through the context.
"""
