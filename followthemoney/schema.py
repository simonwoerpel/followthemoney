from rdflib import URIRef  # type: ignore
from banal import ensure_list, ensure_dict, as_bool

from followthemoney.property import Property
from followthemoney.types import registry
from followthemoney.exc import InvalidData, InvalidModel
from followthemoney.util import gettext, NS


class Schema(object):
    """A type definition for a class of entities that have certain properties.

    Schemata are arranged in a multi-rooted hierarchy: each schema can have multiple
    parent schemata from which it inherits all of their properties, and a schema can
    have descendant child schemata, which, in turn, add further properties. Schemata
    are usually accessed via the model, which holds all available definitions.
    """

    def __init__(self, model, name, data):
        #: Machine-readable name of the schema, used for identification.
        self.name = name
        self.model = model
        self.data = data
        self._label = data.get("label", name)
        self._plural = data.get("plural", self.label)
        self._description = data.get("description")
        self._hash = hash("<Schema(%r)>" % name)

        #: RDF identifier for this schema when it is transformed to a triple term.
        self.uri = URIRef(data.get("rdf", NS[name]))

        #: Do not store or emit entities of this type, it is used only for
        #: inheritance.
        self.abstract = as_bool(data.get("abstract"), False)

        #: Hide this schema in listings.
        self.hidden = as_bool(data.get("hidden"), False)
        self.hidden = self.hidden and not self.abstract

        #: Entities with this type are generated by the system - for example, via
        #: `ingest-file`. The user should not be offered an option to create them
        #: in the interface.
        self.generated = as_bool(data.get("generated"), False)

        #: Try to perform fuzzy matching. Fuzzy similarity search does not
        #: make sense for entities which have a lot of similar names, such
        #: as land plots, assets etc.
        self.matchable = as_bool(data.get("matchable"), True)

        #: Mark a set of properties as important, i.e. they should be shown
        #: first, or in an abridged view of the entity. In Aleph, these properties
        #: are included in tabular entity listings.
        self.featured = ensure_list(data.get("featured"))

        #: Mark a set of properties as required. This is applied only when
        #: an entity is created by the user - bulk created entities will
        #: slip through even if it is technically invalid.
        self.required = ensure_list(data.get("required"))

        #: Mark a set of properties to be used for the entity's caption.
        #: They will be checked in order and the first existant value will
        #: be used.
        self.caption = ensure_list(data.get("caption"))

        # A transform of the entity into an edge for its representation in
        # the context of a property graph representation like Neo4J/Gephi.
        edge = data.get("edge", {})
        self.edge_source = edge.get("source")
        self.edge_target = edge.get("target")

        #: Flag to indicate if this schema should be represented by an edge (rather than
        #: a node) when the data is converted into a property graph.
        self.edge = self.edge_source and self.edge_target
        self.edge_caption = ensure_list(edge.get("caption"))
        self._edge_label = edge.get("label", self._label)

        #: Flag to indicate if the edge should be presented as directed to the user, e.g.
        #: by showing an error at the target end of the edge.
        self.edge_directed = edge.get("directed", True)

        #: Direct parent schemata of this schema.
        self.extends = set()

        #: All parents of this schema (including indirect parents and the schema itself).
        self.schemata = set([self])

        #: All names of :attr:`~schemata`.
        self.names = set([self.name])

        #: Inverse of :attr:`~schemata`, all derived child types of this schema
        #: and their children.
        self.descendants = set()

        #: The full list of properties defined for the entity, including those
        #: inherited from parent schemata.
        self.properties = {}
        for name, prop in data.get("properties", {}).items():
            self.properties[name] = Property(self, name, prop)

    def generate(self):
        """While loading the schema, this function will validate and fully
        load the hierarchy, properties and flags of the definition."""
        for parent in ensure_list(self.data.get("extends")):
            parent = self.model.get(parent)
            parent.generate()

            for name, prop in parent.properties.items():
                if name not in self.properties:
                    self.properties[name] = prop

            self.extends.add(parent)
            for ancestor in parent.schemata:
                self.schemata.add(ancestor)
                self.names.add(ancestor.name)
                ancestor.descendants.add(self)

        for prop in list(self.properties.values()):
            prop.generate()

        for featured in self.featured:
            if self.get(featured) is None:
                raise InvalidModel("Missing featured property: %s" % featured)

        for caption in self.caption:
            if self.get(caption) is None:
                raise InvalidModel("Missing caption property: %s" % caption)

        for required in self.required:
            if self.get(required) is None:
                raise InvalidModel("Missing required property: %s" % required)

        if self.edge:
            if self.source_prop is None:
                msg = "Missing edge source: %s" % self.edge_source
                raise InvalidModel(msg)

            if self.target_prop is None:
                msg = "Missing edge target: %s" % self.edge_target
                raise InvalidModel(msg)

    def _add_reverse(self, data, other):
        name = data.get("name", None)
        if name is None:
            raise InvalidModel("Unnamed reverse: %s" % other)

        prop = self.get(name)
        if prop is None:
            data.update(
                {
                    "type": registry.entity.name,
                    "reverse": {"name": other.name},
                    "range": other.schema.name,
                    "stub": True,
                }
            )
            data["hidden"] = data.get("hidden", other.hidden)
            prop = Property(self, name, data)
            prop.generate()
            self.properties[name] = prop
        return prop

    @property
    def label(self):
        """User-facing name of the schema."""
        return gettext(self._label)

    @property
    def plural(self):
        """Name of the schema to be used in plural constructions."""
        return gettext(self._plural)

    @property
    def description(self):
        """A longer description of the semantics of the schema."""
        return gettext(self._description)

    @property
    def edge_label(self):
        """Description label for edges derived from entities of this schema."""
        return gettext(self._edge_label)

    @property
    def source_prop(self):
        """The entity property to be used as an edge source."""
        return self.get(self.edge_source)

    @property
    def target_prop(self):
        """The entity property to be used as an edge target."""
        return self.get(self.edge_target)

    @property
    def sorted_properties(self):
        """All properties of the schema in the order in which they should be shown
        to the user (alphabetically, with captions and featured properties first)."""
        return sorted(
            self.properties.values(),
            key=lambda p: (
                p.name not in self.caption,
                p.name not in self.featured,
                p.label,
            ),
        )

    @property
    def matchable_schemata(self):
        """Return the set of schemata to which is makes sense to compare this schema.
        For example, it makes no sense to compare a car and a person, but it may make
        sense to compare a legal entity and a company."""
        if not self.matchable:
            return
        # This is used by the cross-referencer to determine what
        # other schemata should be considered for matches. For
        # example, a Company may be compared to a Legal Entity,
        # but it makes no sense to compare it to an Aircraft.
        matchable = set(self.schemata)
        matchable.update(self.descendants)
        for schema in matchable:
            if schema.matchable:
                yield schema

    def is_a(self, other):
        """Check if the schema or one of its parents is the same as the given
        candidate ``other``."""
        return self.model.get(other) in self.schemata

    def get(self, name):
        """Retrieve a property defined for this schema by its name."""
        return self.properties.get(name)

    def validate(self, data):
        """Validate a dictionary against the given schema.
        This will also drop keys which are not valid as properties.
        """
        errors = {}
        properties = ensure_dict(data.get("properties"))
        for name, prop in self.properties.items():
            values = ensure_list(properties.get(name))
            error = prop.validate(values)
            if error is None and not len(values):
                if prop.name in self.required:
                    error = gettext("Required")
            if error is not None:
                errors[name] = error
        if len(errors):
            msg = gettext("Entity validation failed")
            raise InvalidData(msg, errors={"properties": errors})

    def to_dict(self):
        """Return schema metadata, including all properties, in a serializable form."""
        data = {
            "label": self.label,
            "plural": self.plural,
            "schemata": list(sorted(self.names)),
            "extends": list(sorted([e.name for e in self.extends])),
            "properties": {},
        }
        if self.edge_source and self.edge_target:
            data["edge"] = {
                "source": self.edge_source,
                "target": self.edge_target,
                "caption": self.edge_caption,
                "label": self.edge_label,
                "directed": self.edge_directed,
            }
        if len(self.featured):
            data["featured"] = self.featured
        if len(self.required):
            data["required"] = self.required
        if len(self.caption):
            data["caption"] = self.caption
        if self.description:
            data["description"] = self.description
        if self.abstract:
            data["abstract"] = True
        if self.hidden:
            data["hidden"] = True
        if self.generated:
            data["generated"] = True
        if self.matchable:
            data["matchable"] = True
        for name, prop in self.properties.items():
            if prop.schema == self:
                data["properties"][name] = prop.to_dict()
        return data

    def __eq__(self, other):
        """Compare two schemata (via hash)."""
        return self._hash == hash(other)

    def __lt__(self, other):
        return self.name.__lt__(other.name)

    def __hash__(self):
        return self._hash

    def __repr__(self):
        return "<Schema(%r)>" % self.name
