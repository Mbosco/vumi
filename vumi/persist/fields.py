# -*- test-case-name: vumi.persist.tests.test_fields -*-

"""Field types for Vumi's persistence models."""

from datetime import datetime

from vumi.message import VUMI_DATE_FORMAT


class ValidationError(Exception):
    """Raised when a value assigned to a field is invalid."""


class FieldDescriptor(object):
    """Property for getting and setting fields."""

    def __init__(self, key, field):
        self.key = key
        self.field = field

    def setup(self, cls):
        self.cls = cls

    def validate(self, value):
        self.field.validate(value)

    def initialize(self, modelobj, value):
        self.__set__(modelobj, value)

    def set_value(self, modelobj, value):
        """Set the value associated with this descriptor."""
        modelobj._riak_object._data[self.key] = self.field.to_riak(value)

    def get_value(self, modelobj):
        """Get the value associated with this descriptor."""
        raw_value = modelobj._riak_object._data.get(self.key)
        return self.field.from_riak(raw_value)

    def __repr__(self):
        return "<%s key=%s field=%r>" % (self.__class__.__name__, self.key,
                                         self.field)

    def __get__(self, instance, owner):
        if instance is None:
            return self.field
        return self.get_value(instance)

    def __set__(self, instance, value):
        # instance can never be None here
        self.validate(value)
        self.set_value(instance, value)


class Field(object):
    """Base class for model attributes / fields.

    :param object default:
        Default value for the field. The default default is None.
    :param boolean null:
        Whether None is allowed as a value. Default is False (which
        means the field must either be specified explicitly or by
        a non-None default).
    """

    descriptor_class = FieldDescriptor
    # whether an attempt should be made to initialize the field on
    # model instance creation
    initializable = True

    def __init__(self, default=None, null=False):
        self.default = default
        self.null = null

    def get_descriptor(self, key):
        return self.descriptor_class(key, self)

    def validate(self, value):
        """Validate a value.

        Checks null values and calls .validate() for non-null
        values. Raises ValidationError if a value is invalid.
        """
        if not self.null and value is None:
            raise ValidationError("None is not allowed as a value for non-null"
                                  " fields.")
        if value is not None:
            self.custom_validate(value)

    def custom_validate(self, value):
        """Check whether a non-null value is valid for this field."""
        pass

    def to_riak(self, value):
        return self.custom_to_riak(value) if value is not None else None

    def custom_to_riak(self, value):
        """Convert a non-None value to something storable by Riak."""
        return value

    def from_riak(self, raw_value):
        return (self.custom_from_riak(raw_value)
                if raw_value is not None else None)

    def custom_from_riak(self, raw_value):
        """Convert a non-None value stored by Riak to Python."""
        return raw_value


class Integer(Field):
    """Field that accepts integers.

    Additional parameters:

    :param integer min:
        Minimum allowed value (default is `None` which indicates no minimum).
    :param integer max:
        Maximum allowed value (default is `None` which indicates no maximum).
    """
    def __init__(self, min=None, max=None, **kw):
        super(Integer, self).__init__(**kw)
        self.min = min
        self.max = max

    def custom_validate(self, value):
        if not isinstance(value, (int, long)):
            raise ValidationError("Value %r is not an integer." % (value,))
        if self.min is not None and value < self.min:
            raise ValidationError("Value %r too low (minimum value is %d)."
                                  % (value, self.min))
        if self.max is not None and value > self.max:
            raise ValidationError("Value %r too high (maximum value is %d)."
                                  % (value, self.max))


class Unicode(Field):
    """Field that accepts unicode strings.

    Additional parameters:

    :param integer max_length:
        Maximum allowed length (default is `None` which indicates no maximum).
    """
    def __init__(self, max_length=None, **kw):
        super(Unicode, self).__init__(**kw)
        self.max_length = max_length

    def custom_validate(self, value):
        if not isinstance(value, unicode):
            raise ValidationError("Value %r is not a unicode string."
                                  % (value,))
        if self.max_length is not None and len(value) > self.max_length:
            raise ValidationError("Value %r too long (maximum length is %d)."
                                  % (value, self.max_length))


class Tag(Field):
    """Field that represents a Vumi tag."""
    def custom_validate(self, value):
        if not isinstance(value, tuple) or len(value) != 2:
            raise ValidationError("Tags %r should be a (pool, tag_name)"
                                  " tuple" % (value,))

    def custom_to_riak(self, value):
        return list(value)

    def custom_from_riak(self, value):
        return tuple(value)


class Timestamp(Field):
    """Field that stores a datetime."""
    def custom_validate(self, value):
        if not isinstance(value, datetime):
            raise ValidationError("Timestamp field expects a datetime.")

    def custom_to_riak(self, value):
        return value.strftime(VUMI_DATE_FORMAT)

    def custom_from_riak(self, value):
        return datetime.strptime(value, VUMI_DATE_FORMAT)


class VumiMessageDescriptor(FieldDescriptor):
    """Property for getting and setting fields."""

    def setup(self, cls):
        super(VumiMessageDescriptor, self).setup(cls)
        if self.field.prefix is None:
            self.prefix = "%s." % self.key
        else:
            self.prefix = self.field.prefix

    def _clear_keys(self, modelobj):
        for key in modelobj._riak_object._data.keys():
            if key.startswith(self.prefix):
                del modelobj._riak_object._data[key]

    def _timestamp_to_json(self, dt):
        return dt.strftime(VUMI_DATE_FORMAT)

    def _timestamp_from_json(self, value):
        return datetime.strptime(value, VUMI_DATE_FORMAT)

    def set_value(self, modelobj, msg):
        """Set the value associated with this descriptor."""
        self._clear_keys(modelobj)
        if msg is None:
            return
        for key, value in msg.payload.iteritems():
            # TODO: timestamp as datetime in payload must die.
            if key == "timestamp":
                value = self._timestamp_to_json(value)
            full_key = "%s%s" % (self.prefix, key)
            modelobj._riak_object._data[full_key] = value

    def get_value(self, modelobj):
        """Get the value associated with this descriptor."""
        payload = {}
        for key, value in modelobj._riak_object._data.iteritems():
            if key.startswith(self.prefix):
                key = key[len(self.prefix):]
                # TODO: timestamp as datetime in payload must die.
                if key == "timestamp":
                    value = self._timestamp_from_json(value)
                payload[key] = value
        return self.field.message_class(**payload) if payload else None


class VumiMessage(Field):
    """Field that represents a Vumi message.

    Additional parameters:

    :param class message_class:
        The class of the message objects being stored.
        Usually one of Message, TransportUserMessage or TransportEvent.
    :param string prefix:
        The prefix to use when storing message payload keys in Riak. Default is
        the name of the field followed by a dot ('.').
    """
    descriptor_class = VumiMessageDescriptor

    def __init__(self, message_class, prefix=None, **kw):
        super(VumiMessage, self).__init__(**kw)
        self.message_class = message_class
        self.prefix = prefix

    def custom_validate(self, value):
        if not isinstance(value, self.message_class):
            raise ValidationError("Message %r should be an instance of %r"
                                  % (value, self.message_class))


class FieldWithSubtype(Field):
    """Base class for a field that is a collection of other fields of a
    single type.

    :param Field field_type:
        The field specification for the dynamic values. Default is Unicode().
    """
    def __init__(self, field_type=None, **kw):
        super(FieldWithSubtype, self).__init__(**kw)
        if field_type is None:
            field_type = Unicode()
        if field_type.descriptor_class is not FieldDescriptor:
            raise RuntimeError("Dynamic fields only supports fields that"
                               " that use the basic FieldDescriptor class")
        self.field_type = field_type

    def validate(self, value):
        self.field_type.validate(value)

    def to_riak(self, value):
        return self.field_type.to_riak(value)

    def from_riak(self, value):
        return self.field_type.from_riak(value)


class DynamicDescriptor(FieldDescriptor):
    """A field descriptor for dynamic fields."""
    def setup(self, cls):
        super(DynamicDescriptor, self).setup(cls)
        if self.field.prefix is None:
            self.prefix = "%s." % self.key
        else:
            self.prefix = self.field.prefix

    def get_value(self, modelobj):
        return DynamicProxy(self, modelobj)

    def set_value(self, modelobj, value):
        raise RuntimeError("DynamicDescriptors should never be assigned to.")

    def get_dynamic_value(self, modelobj, dynamic_key):
        key = self.prefix + dynamic_key
        return self.field.from_riak(modelobj._riak_object._data.get(key))

    def set_dynamic_value(self, modelobj, dynamic_key, value):
        self.field.validate(value)
        key = self.prefix + dynamic_key
        modelobj._riak_object._data[key] = self.field.to_riak(value)


class DynamicProxy(object):
    def __init__(self, descriptor, modelobj):
        self.__dict__['_descriptor_modelobj_'] = (descriptor, modelobj)

    def __getattr__(self, key):
        descriptor, modelobj = self._descriptor_modelobj_
        return descriptor.get_dynamic_value(modelobj, key)

    def __setattr__(self, key, value):
        descriptor, modelobj = self._descriptor_modelobj_
        descriptor.set_dynamic_value(modelobj, key, value)


class Dynamic(FieldWithSubtype):
    """A field that allows sub-fields to be added dynamically.

    :param Field field_type:
        The field specification for the dynamic values. Default is Unicode().
    :param string prefix:
        The prefix to use when storing these values in Riak. Default is
        the name of the field followed by a dot ('.').
    """
    descriptor_class = DynamicDescriptor
    initializable = False

    def __init__(self, field_type=None, prefix=None):
        super(Dynamic, self).__init__(field_type=field_type)
        self.prefix = prefix


class ListOfDescriptor(FieldDescriptor):
    """A field descriptor for ListOf fields."""

    def get_value(self, modelobj):
        return ListProxy(self, modelobj)

    def __set__(self, modelobj, values):
        # override __set__ to do custom validation
        for value in values:
            self.field.validate(value)
        raw_values = [self.field.to_riak(value) for value in values]
        modelobj._riak_object._data[self.key] = raw_values

    def _ensure_list(self, modelobj):
        if self.key not in modelobj._riak_object._data:
            modelobj._riak_object._data[self.key] = []

    def get_list_item(self, modelobj, list_idx):
        raw_list = modelobj._riak_object._data.get(self.key, [])
        raw_item = raw_list[list_idx]
        return self.field.from_riak(raw_item)

    def set_list_item(self, modelobj, list_idx, value):
        self.field.validate(value)
        raw_value = self.field.to_riak(value)
        self._ensure_list(modelobj)
        modelobj._riak_object._data[self.key][list_idx] = raw_value

    def del_list_item(self, modelobj, list_idx):
        raw_list = modelobj._riak_object._data.get(self.key, [])
        del raw_list[list_idx]

    def append_list_item(self, modelobj, value):
        self.field.validate(value)
        raw_value = self.field.to_riak(value)
        self._ensure_list(modelobj)
        modelobj._riak_object._data[self.key].append(raw_value)

    def extend_list(self, modelobj, values):
        for value in values:
            self.field.validate(value)
        raw_values = [self.field.to_riak(value) for value in values]
        self._ensure_list(modelobj)
        modelobj._riak_object._data[self.key].extend(raw_values)

    def iter_list(self, modelobj):
        raw_list = modelobj._riak_object._data.get(self.key, [])
        for raw_value in raw_list:
            yield self.field.from_riak(raw_value)


class ListProxy(object):
    def __init__(self, descriptor, modelobj):
        self._descriptor = descriptor
        self._modelobj = modelobj

    def __getitem__(self, idx):
        return self._descriptor.get_list_item(self._modelobj, idx)

    def __setitem__(self, idx, value):
        self._descriptor.set_list_item(self._modelobj, idx, value)

    def __delitem__(self, idx):
        self._descriptor.del_list_item(self._modelobj, idx)

    def append(self, idx):
        self._descriptor.append_list_item(self._modelobj, idx)

    def extend(self, values):
        self._descriptor.extend_list(self._modelobj, values)

    def __iter__(self):
        return self._descriptor.iter_list(self._modelobj)


class ListOf(FieldWithSubtype):
    """A field that contains a list of values of some other type.

    :param Field field_type:
    The field specification for the dynamic values. Default is Unicode().
    """
    descriptor_class = ListOfDescriptor

    def __init__(self, field_type=None):
        super(ListOf, self).__init__(field_type=field_type, default=list)


class ForeignKeyDescriptor(FieldDescriptor):
    def setup(self, cls):
        super(ForeignKeyDescriptor, self).setup(cls)
        self.othercls = self.field.othercls
        if self.field.index is None:
            self.index_name = "%s_bin" % self.key
        else:
            self.index_name = self.field.index

        reverse_lookup_name = cls.__name__.lower() + "s"
        self.othercls.backlinks.declare_backlink(reverse_lookup_name,
                                                 self.reverse_lookup)

    def reverse_lookup(self, modelobj, manager=None):
        if manager is None:
            manager = modelobj.manager
        mr = manager.riak_map_reduce()
        bucket = manager.bucket_prefix + self.cls.bucket
        mr.index(bucket, self.index_name, modelobj.key)
        return manager.run_map_reduce(mr, self.map_lookup_result)

    def map_lookup_result(self, manager, result):
        return self.cls.load(manager, result.get_key())

    def get_value(self, modelobj):
        return ForeignKeyProxy(self, modelobj)

    def get_foreign_key(self, modelobj):
        indexes = modelobj._riak_object.get_indexes(self.index_name)
        if not indexes:
            return None
        key = indexes[0]
        return key

    def set_foreign_key(self, modelobj, foreign_key):
        modelobj._riak_object.remove_index(self.index_name)
        if foreign_key is not None:
            modelobj._riak_object.add_index(self.index_name, foreign_key)

    def get_foreign_object(self, modelobj, manager=None):
        key = self.get_foreign_key(modelobj)
        if key is None:
            return None
        if manager is None:
            manager = modelobj.manager
        return self.othercls.load(manager, key)

    def initialize(self, modelobj, value):
        if isinstance(value, basestring):
            self.set_foreign_key(modelobj, value)
        else:
            self.set_foreign_object(modelobj, value)

    def set_value(self, modelobj, value):
        raise RuntimeError("ForeignKeyDescriptors should never be assigned"
                           " to.")

    def set_foreign_object(self, modelobj, otherobj):
        self.validate(otherobj)
        modelobj._riak_object.remove_index(self.index_name)
        if otherobj is not None:
            modelobj._riak_object.add_index(self.index_name, otherobj.key)


class ForeignKeyProxy(object):
    def __init__(self, descriptor, modelobj):
        self._descriptor = descriptor
        self._modelobj = modelobj

    def _get_key(self):
        return self._descriptor.get_foreign_key(self._modelobj)

    def _set_key(self, foreign_key):
        return self._descriptor.set_foreign_key(self._modelobj, foreign_key)

    key = property(fget=_get_key, fset=_set_key)

    def get(self, manager=None):
        return self._descriptor.get_foreign_object(self._modelobj, manager)

    def set(self, otherobj):
        self._descriptor.set_foreign_object(self._modelobj, otherobj)


class ForeignKey(Field):
    """A field that links to another class.

    Additional parameters:

    :param Model othercls:
        The type of model linked to.
    :param string index:
        The name to use for the index. The default is the field name
        followed by _bin.
    """
    descriptor_class = ForeignKeyDescriptor

    def __init__(self, othercls, index=None, **kw):
        super(ForeignKey, self).__init__(**kw)
        self.othercls = othercls
        self.index = index

    def custom_validate(self, value):
        if not isinstance(value, self.othercls):
            raise ValidationError("ForeignKey requires a %r instance" %
                                  (self.othercls,))


class ManyToManyDescriptor(ForeignKeyDescriptor):

    def get_value(self, modelobj):
        return ManyToManyProxy(self, modelobj)

    def set_value(self, modelobj, value):
        raise RuntimeError("ManyToManyDescriptors should never be assigned"
                           " to.")

    def get_foreign_keys(self, modelobj):
        indexes = modelobj._riak_object.get_indexes(self.index_name)
        return indexes

    def add_foreign_key(self, modelobj, foreign_key):
        modelobj._riak_object.add_index(self.index_name, foreign_key)

    def remove_foreign_key(self, modelobj, foreign_key):
        modelobj._riak_object.remove_index(self.index_name, foreign_key)

    def get_foreign_objects(self, modelobj, manager=None):
        keys = self.get_foreign_keys(modelobj)
        if manager is None:
            manager = modelobj.manager
        return manager.load_list(self.othercls, keys)

    def add_foreign_object(self, modelobj, otherobj):
        self.validate(otherobj)
        self.add_foreign_key(modelobj, otherobj.key)

    def remove_foreign_object(self, modelobj, otherobj):
        self.validate(otherobj)
        self.remove_foreign_key(modelobj, otherobj.key)

    def clear_keys(self, modelobj):
        modelobj._riak_object.remove_index(self.index_name)


class ManyToManyProxy(object):
    def __init__(self, descriptor, modelobj):
        self._descriptor = descriptor
        self._modelobj = modelobj

    def keys(self):
        return self._descriptor.get_foreign_keys(self._modelobj)

    def add_key(self, foreign_key):
        self._descriptor.add_foreign_key(self._modelobj, foreign_key)

    def remove_key(self, foreign_key):
        self._descriptor.remove_foreign_key(self._modelobj, foreign_key)

    def get_all(self, manager=None):
        return self._descriptor.get_foreign_objects(self._modelobj, manager)

    def add(self, otherobj):
        self._descriptor.add_foreign_object(self._modelobj, otherobj)

    def remove(self, otherobj):
        self._descriptor.remove_foreign_object(self._modelobj, otherobj)

    def clear(self):
        self._descriptor.clear_keys(self._modelobj)


class ManyToMany(ForeignKey):
    """A field that links to multiple instances of another class.

    :param Model othercls:
        The type of model linked to.
    :param string index:
        The name to use for the index. The default is the field name
        followed by _bin.
    """
    descriptor_class = ManyToManyDescriptor
    initializable = False

    def __init__(self, othercls, index=None):
        super(ManyToMany, self).__init__(othercls, index)