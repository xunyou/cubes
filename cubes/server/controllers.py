from werkzeug.wrappers import Response
from werkzeug.utils import redirect
from werkzeug.exceptions import NotFound
import sqlalchemy
import decimal
import os.path

version = "0.1"
api_version = "1"


TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), 'templates')

import cubes
import json

class FixingEncoder(json.JSONEncoder):
    def default(self, o):
        if type(o) == decimal.Decimal:
            return float(o)
        else:
            return json.JSONEncoder.default(self, o)

class ApplicationController(object):
    def __init__(self, config):
        self.model = cubes.load_model(config["model"])
        self.cube_name = config["cube"]
        self.cube = self.model.cube(self.cube_name)

        if "view" in config:
            self.view_name = config["view"]
        else:
            self.view_name = self.cube_name

        self.dburl = config["dburl"]

        self.params = None
        self.query = None
        self.browser = None
        
    def index(self):
        handle = open(os.path.join(TEMPLATE_PATH, "index.html"))
        template = handle.read()
        handle.close()
        
        context = {"version": version, "api_version": api_version}
        
        context["model"] = self.model.name
        array = []
        for cube in self.model.cubes.values():
            array.append(cube.name)
            
        if array:
            context["cubes"] = ", ".join(array)
        else:
            context["cubes"] = "<none>"
        
        doc = template.format(**context)
        
        return Response(doc, mimetype = 'text/html')
    
    def version(self):
        response = {
            "server_version": version,
            "api_version": api_version
        }

        return self.json_response(response)

    def json_response(self, obj):

        encoder = FixingEncoder(indent = 4)
        reply = encoder.iterencode(obj)

        return Response(reply, mimetype='application/json')
        
    def initialize(self):
        pass
        
    def finalize(self):
        pass
        
    def error(self, message = None, exception = None, status = None):
        if not message:
            message = "An unknown error occured"
            
        error = {}
        error["message"] = message
        if exception:
            error["reason"] = str(exception)

        string = json.dumps({"error": error})
        
        if not status:
            status = 500
        
        return Response(string, mimetype='application/json', status = status)
        
class ModelController(ApplicationController):

    def show(self):
        return self.json_response(self.model.to_dict())

    def dimension(self):
        dim_name = self.params["name"]

        dim = self.model.dimension(dim_name)
        return self.json_response(dim.to_dict())

    def _cube_dict(self, cube):
        d = cube.to_dict(expand_dimensions = True, 
                         full_attribute_names = True,
                         with_mappings = False)

        # array = []
        # for dim in cube.dimensions:
        #     array.append(dim.to_dict())
        #     
        # d["dimensions"] = array
        return d

    def get_default_cube(self):
        return self.json_response(self._cube_dict(self.cube))

    def get_cube(self):
        cube_name = self.params["name"]

        cube = self.model.cube(cube_name)
        return self.json_response(self._cube_dict(cube))
        
    def dimension_levels(self):
        dim_name = self.params["name"]
        dim = self.model.dimension(dim_name)
        levels = [l.to_dict() for l in dim.default_hierarchy.levels]

        string = json.dumps(levels)

        return Response(string)

    def dimension_level_names(self):
        dim_name = self.params["name"]
        dim = self.model.dimension(dim_name)

        return self.json_response(dim.default_hierarchy.level_names)

class AggregationController(ApplicationController):
    def initialize(self):

        self.engine = sqlalchemy.create_engine(self.dburl)
        self.connection = self.engine.connect()

        self.browser = cubes.backends.SimpleSQLBrowser(self.cube, self.connection, self.view_name)

    def finalize(self):
        self.connection.close()
    
    def prepare_cuboid(self):
        cut_string = self.request.args.get("cut")

        if cut_string:
            cuts = cubes.cuts_from_string(cut_string)
        else:
            cuts = []

        self.cuboid = cubes.Cuboid(self.browser, cuts)
        
    def aggregate(self):
        self.prepare_cuboid()

        drilldown = self.request.args.getlist("drilldown")

        try:
            result = self.cuboid.aggregate(drilldown = drilldown)
        except Exception, e:
            return self.error("Aggregation failed", e)

        return Response(result.as_json())

    def facts(self):
        self.prepare_cuboid()

        try:
            result = self.cuboid.facts()
        except Exception, e:
            return self.error("Fetching facts failed", e)

        return self.json_response(result)

    def fact(self):
        fact_id = self.params["id"]

        try:
            fact = self.browser.fact(fact_id)
        except Exception, e:
            return self.error("Fetching single fact failed", e)

        if fact:
            return self.json_response(fact)
        else:
            return self.error("No fact with id=%s" % fact_id, status = 404)
        