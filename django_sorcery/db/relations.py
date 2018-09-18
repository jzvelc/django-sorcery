# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals
from itertools import chain

import sqlalchemy as sa
from sqlalchemy.ext.declarative import declared_attr

from ..utils import setdefaultattr, suppress
from .signals import declare_first


class RelationsMixin(object):
    def OneToMany(self, remote_cls, **kwargs):
        """
        Use an event to build one-to-many relationship on a model and auto generates foreign key relationship from the
        remote table::

            class ModelOne(db.Model):
                pk = db.Column(.., primary_key=True)
                m2 = db.OneToMany("ModelTwo", ...)

            class ModelTwo(db.Model):
                pk = db.Column(.., primary_key=True)
                ...

            will create ModelTwo.m1_pk automatically for the relationship
        """

        @declared_attr
        def o2m(cls):
            """
            one to many relationship attribute for declarative
            """
            rels = setdefaultattr(cls, "_relationships", set())
            kwargs.setdefault("info", {}).update(self._get_kwargs_for_relation(kwargs))
            kwargs["uselist"] = True
            backref = kwargs.get("backref")
            backref_kwargs = None
            if backref:
                if isinstance(backref, tuple):
                    with suppress(Exception):
                        backref, backref_kwargs = backref

                backref_kwargs = backref_kwargs or {}

                backref_kwargs["uselist"] = False
                kwargs["backref"] = (backref, backref_kwargs)

            rel = self.relationship(remote_cls, **kwargs)
            rel.direction = sa.orm.interfaces.ONETOMANY
            rels.add(rel)
            return rel

        return o2m

    def ManyToOne(self, remote_cls, **kwargs):
        """
        Use an event to build many-to-one relationship on a model and auto generates foreign key relationship on the
        remote table::

            class ModelOne(db.Model):
                pk = db.Column(.., primary_key=True)
                m2 = db.ManyToOne("ModelTwo", ...)

            class ModelTwo(db.Model):
                pk = db.Column(.., primary_key=True)
                ...

        will create ModelOne.m2_pk automatically for the relationship
        """

        @declared_attr
        def m2o(cls):
            """
            many to one relationship attribute for declarative
            """
            rels = setdefaultattr(cls, "_relationships", set())
            kwargs.setdefault("info", {}).update(self._get_kwargs_for_relation(kwargs))
            kwargs["uselist"] = False
            backref = kwargs.get("backref")
            if backref:
                backref_kwargs = None
                if isinstance(backref, tuple):
                    with suppress(Exception):
                        backref, backref_kwargs = backref

                backref_kwargs = backref_kwargs or {}

                backref_kwargs["uselist"] = True
                kwargs["backref"] = self.backref(backref, **backref_kwargs)

            rel = self.relationship(remote_cls, **kwargs)
            rel.direction = sa.orm.interfaces.MANYTOONE
            rels.add(rel)
            return rel

        return m2o

    def ManyToMany(self, remote_cls, table_name=None, **kwargs):
        """
        Use an event to build many-to-many relationship on a model and auto generates an association table or if a
        model is provided as secondary argument::

            class ModelOne(db.Model):
                pk = db.Column(.., primary_key=True)
                m2s = db.ManyToMany("ModelTwo", backref="m1s", table_name='m1m2s', ...)

            class ModelTwo(db.Model):
                pk = db.Column(.., primary_key=True)
                ...

        or with back_populates::

            class ModelOne(db.Model):
                pk = db.Column(.., primary_key=True)
                m2s = db.ManyToMany("ModelTwo", back_populates="m1s", table_name='m1m2s', ...)

            class ModelTwo(db.Model):
                pk = db.Column(.., primary_key=True)
                m1s = db.ManyToMany("ModelOne", back_populates="m2s", table_name='m1m2s', ...)

        will create ModelOne.m2s and ModelTwo.m1s relationship thru a provided secondary argument. If no secondary argument
        is provided, table_name is required as it will be used for the autogenerated association table.

        In the case of back_populates you have to provide the same table_name argument on both many-to-many
        declarations
        """

        @declared_attr
        def m2m(cls):
            """
            many to many relationship attribute for declarative
            """
            if "secondary" not in kwargs and table_name is None:
                raise sa.exc.ArgumentError(
                    "You need to provide secondary or table_name for the relation for the association table "
                    "that will be generated"
                )

            rels = setdefaultattr(cls, "_relationships", set())
            info = kwargs.setdefault("info", {})
            info.update(self._get_kwargs_for_relation(kwargs))
            info.update(self._get_kwargs_for_relation(kwargs, "table_"))
            if table_name:
                info["table_name"] = table_name

            kwargs["uselist"] = True

            backref = kwargs.get("backref")
            backref_kwargs = None
            if backref:
                if isinstance(backref, tuple):
                    with suppress(Exception):
                        backref, backref_kwargs = backref

                backref_kwargs = backref_kwargs or {}

                backref_kwargs["uselist"] = True
                kwargs["backref"] = self.backref(backref, **backref_kwargs)

            rel = self.relationship(remote_cls, **kwargs)
            rel.direction = sa.orm.interfaces.MANYTOMANY
            rels.add(rel)
            return rel

        return m2m

    def _get_kwargs_for_relation(self, kwargs, prefix="fk_"):
        opts = {}
        for key in list(kwargs.keys()):
            if key.startswith(prefix):
                opts[key] = kwargs.pop(key)
        return opts


def _add_foreign_keys(cls, parent_cls, relation):
    """
    Generate fk columns and constraint to the remote class from a relationship
    """
    fk_kwargs = {key[3:]: val for key, val in relation.info.items() if key.startswith("fk_")}
    fk_prefix = fk_kwargs.pop("prefix", "_")
    fk_nullable = fk_kwargs.pop("nullable", True)
    fk_key = fk_kwargs.pop("key", None)

    if not fk_key:
        if relation.direction == sa.orm.interfaces.MANYTOONE:
            fk_key = relation.key.lower()
        elif relation.backref:
            backref, _ = relation.backref
            fk_key = backref.lower()
        else:
            fk_key = parent_cls.__name__.lower()

    cols = {}
    cols_created = False
    for pk_column in parent_cls.__table__.primary_key:
        pk_attr = parent_cls.__mapper__.get_property_by_column(pk_column)
        col_name = "_".join(filter(None, [fk_key, pk_column.name]))
        attr = "{}{}".format(fk_prefix, "_".join(filter(None, [fk_key, pk_attr.key])))

        if col_name not in cls.__table__.columns and not hasattr(cls, attr):
            fk_column = sa.Column(col_name, pk_column.type, nullable=fk_nullable)
            setattr(cls, attr, fk_column)
            cols_created = True
        else:
            fk_column = cls.__table__.columns[col_name]

        cols[pk_column] = fk_column

    relation._user_defined_foreign_keys = cols.values()

    if cols_created:
        # pk and fk ordering must match for foreign key constraint
        pks, fks = [], []
        for pk in cols:
            pks.append(pk)
            fks.append(cols[pk])

        constraint = sa.ForeignKeyConstraint(fks, pks, **fk_kwargs)
        cls.__table__.append_constraint(constraint)


def _add_association_table(cls, child_cls, relation):
    """
    Generate association table and fk constraints to satisfy a many-to-many relation
    """
    if relation.secondary is not None:
        return

    table_name = relation.info.get("table_name")
    relation.secondary = cls.metadata.tables.get(table_name)
    if relation.secondary is not None:
        return

    fk_kwargs = {key[3:]: val for key, val in relation.info.items() if key.startswith("fk_")}
    table_kwargs = {key[6:]: val for key, val in relation.info.items() if key.startswith("table_")}
    table_kwargs.pop("name", None)

    column_map = {}
    for pk_column in chain(cls.__mapper__.primary_key, child_cls.__table__.primary_key):
        col_name = "_".join(filter(None, [pk_column.table.name.lower(), pk_column.name]))
        col = sa.Column(col_name, pk_column.type, primary_key=True)
        column_map.setdefault(pk_column.table, []).append(col)

    table_args = list(chain(*column_map.values()))

    for table, columns in column_map.items():
        table_args.append(sa.ForeignKeyConstraint(columns, table.primary_key, **fk_kwargs))

    relation.secondary = sa.Table(table_name, cls.metadata, *table_args, schema=cls.__table__.schema, **table_kwargs)


@declare_first.connect
def declare_first_relationships_handler(cls):
    """
    Declare first signal handler which connects relationships on the class

    Can be called multiple times so once relationships are set,
    they are removed from model
    """
    rels = getattr(cls, "_relationships", set())

    for relation in rels:
        if relation.direction == sa.orm.interfaces.ONETOMANY:
            _add_foreign_keys(relation.mapper.class_, cls, relation)
        elif relation.direction == sa.orm.interfaces.MANYTOONE:
            _add_foreign_keys(cls, relation.mapper.class_, relation)
        elif relation.direction == sa.orm.interfaces.MANYTOMANY:
            _add_association_table(cls, relation.mapper.class_, relation)

    rels.clear()
