from flask_restx import Namespace, Resource
from api.database import get_cursor

ns = Namespace("health", description="Health check")


@ns.route("")
class HealthCheck(Resource):
    def get(self):
        try:
            with get_cursor() as cur:
                cur.execute("SELECT 1")
            return {"status": "ok", "database": "ok"}, 200
        except Exception as e:
            return {"status": "error", "database": str(e)}, 503
