# Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
# http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.
"""This module contains the inteface for controlling how configuration
is loaded.
"""
import os


def create_botocore_default_config_mapping(chain_builder):
    return {
        'profile': chain_builder.create_config_chain(
            instance_name='profile',
            env_var_names=['AWS_DEFAULT_PROFILE', 'AWS_PROFILE'],
        ),
        'region': chain_builder.create_config_chain(
            instance_name='region',
            env_var_names='AWS_DEFAULT_REGION',
            config_property_name='region',
            default=None,
        ),
        'data_path': chain_builder.create_config_chain(
            instance_name='data_path',
            env_var_names='AWS_DATA_PATH',
            config_property_name='data_path',
            default=None,
        ),
        'config_file': chain_builder.create_config_chain(
            instance_name='config_file',
            env_var_names='AWS_CONFIG_FILE',
            default='~/.aws/config',
        ),
        'ca_bundle': chain_builder.create_config_chain(
            instance_name='ca_bundle',
            env_var_names='AWS_CA_BUNDLE',
            config_property_name='ca_bundle',
        ),
        'api_versions': chain_builder.create_config_chain(
            instance_name='api_versions',
            config_property_name='api_versions',
            default={},
        ),
        'credentials_file': chain_builder.create_config_chain(
            instance_name='credentials_file',
            env_var_names='AWS_SHARED_CREDENTIALS_FILE',
            default='~/.aws/credentials',
        ),
        'metadata_service_timeout': chain_builder.create_config_chain(
            instance_name='metadata_service_timeout',
            env_var_names='AWS_METADATA_SERVICE_TIMEOUT',
            config_property_name='metadata_service_timeout',
            default=1,
            conversion_func=int,
        ),
        'metadata_service_num_attempts': chain_builder.create_config_chain(
            instance_name='metadata_service_num_attempts',
            env_var_names='AWS_METADATA_SERVICE_NUM_ATTEMPTS',
            config_property_name='metadata_service_num_attempts',
            default=1,
            conversion_func=int,
        ),
        'parameter_validation': chain_builder.create_config_chain(
            instance_name='parameter_validation',
            config_property_name='parameter_validation',
            default=True,
        ),
    }


class ConfigChainFactory(object):
    """Factory class to create our most common configuration chain case.

    This is a convenience class to construct configuration chains that follow
    our most common pattern. This is to prevent ordering them incorrectly,
    and to make the config chain construction more readable.
    """
    def __init__(self, session, environ=None):
        """Initialize a ConfigChainFactory.

        :type session: :class:`botocore.session.Session`
        :param session: This is the session that should be used to look up
            values from the config file.

        :type environ: dict
        :param environ: A mapping to use for environment variables. If this
            is not provided it will default to use os.environ.
        """
        self._session = session
        if environ is None:
            environ = os.environ
        self._environ = environ

    def create_config_chain(self, instance_name=None, env_var_names=None,
                            config_property_name=None, default=None,
                            conversion_func=None):
        """Build a config chain following the standard botocore pattern.

        In botocore most of our config chains follow the the precendence:
        session_instance_variables, environment, config_file, default_value.

        This is a convenience function for creating a chain that follow
        that precendence.

        :type instance_name: str
        :param instance_name: This indicates what session instance variable
            corresponds to this config value. If it is None it will not be
            added to the chain.

        :type env_var_names: str or list of str or None
        :param env_var_names: One or more environment variable names to
            search for this value. They are searched in order. If it is None
            it will not be added to the chain.

        :type config_property_name: str or None
        :param config_property_name: The string name of the key in the config
            file for this config option. If it is None it will not be added to
            the chain.

        :type default: Any
        :param default: Any constant value to be returned.

        :type conversion_func: None or callable
        :param conversion_func: If this value is None then it has no effect on
            the return type. Otherwise, it is treated as a function that will
            conversion_func our provided type.

        :rvalue: ConfigChain
        :returns: A ConfigChain that resolves in the order env_var_names ->
            config_property_name -> default. Any values that were none are
            omitted form the chain.
        """
        providers = []
        if instance_name is not None:
            providers.append(
                InstanceVarProvider(
                    instance_var=instance_name,
                    session=self._session
                )
            )
        if env_var_names is not None:
            providers.append(
                EnvironmentProvider(
                    names=env_var_names,
                    env=self._environ,
                )
            )
        if config_property_name is not None:
            providers.append(
                ScopedConfigProvider(
                    config_var_name=config_property_name,
                    session=self._session,
                )
            )
        if default is not None:
            providers.append(ConstantProvider(value=default))

        return ChainProvider(
            providers=providers,
            conversion_func=conversion_func,
        )


class ConfigValueStore(object):
    """The ConfigValueStore object stores configuration values."""
    def __init__(self, mapping=None):
        """Initialize a ConfigValueStore.

        :type mapping: dict
        :param mapping: The mapping parameter is a map of string to a subclass
            of BaseProvider. When a config variable is asked for via the
            get_config_variable method, the corresponding provider will be
            invoked to load the value.
        """
        self._overrides = {}
        self._mapping = {}
        if mapping is not None:
            for logical_name, provider in mapping.items():
                self.set_config_provider(logical_name, provider)

    def get_config_variable(self, logical_name):
        """
        Retrieve the value associeated with the specified logical_name
        from the corresponding provider. If no value is found None will
        be returned.

        :type logical_name: str
        :param logical_name: The logical name of the session variable
            you want to retrieve.  This name will be mapped to the
            appropriate environment variable name for this session as
            well as the appropriate config file entry.

        :returns: value of variable or None if not defined.
        """
        if logical_name in self._overrides:
            return self._overrides[logical_name]
        if logical_name not in self._mapping:
            return None
        provider = self._mapping[logical_name]
        return provider.provide()

    def set_config_variable(self, logical_name, value):
        """Set a configuration variable to a specific value.

        By using this method, you can override the normal lookup
        process used in ``get_config_variable`` by explicitly setting
        a value.  Subsequent calls to ``get_config_variable`` will
        use the ``value``.  This gives you per-session specific
        configuration values.

        ::
            >>> # Assume logical name 'foo' maps to env var 'FOO'
            >>> os.environ['FOO'] = 'myvalue'
            >>> s.get_config_variable('foo')
            'myvalue'
            >>> s.set_config_variable('foo', 'othervalue')
            >>> s.get_config_variable('foo')
            'othervalue'

        :type logical_name: str
        :param logical_name: The logical name of the session variable
            you want to set.  These are the keys in ``SESSION_VARIABLES``.

        :param value: The value to associate with the config variable.
        """
        self._overrides[logical_name] = value

    def clear_config_variable(self, logical_name):
        """Remove an override config variable from the session.

        :type logical_name: str
        :param logical_name: The name of the parameter to clear the override
            value from.
        """
        self._overrides.pop(logical_name, None)

    def set_config_provider(self, logical_name, provider):
        """Set the provider for a config value.

        This provides control over how a particular configuration value is
        loaded. This replaces the provider for ``logical_name`` with the new
        ``provider``.

        :type logical_name: str
        :param logical_name: The name of the config value to change the config
            provider for.

        :type provider: :class:`botocore.configprovider.BaseProvider`
        :param provider: The new provider that should be responsible for
            providing a value for the config named ``logical_name``.
        """
        self._mapping[logical_name] = provider


class BaseProvider(object):
    """Base class for configuration value providers.

    A configuration provider has some method of providing a configuration
    value.
    """
    def provide(self):
        """Provide a config value."""
        raise NotImplementedError('provide')


class ChainProvider(BaseProvider):
    """This provider wraps one or more other providers.

    Each provider in the chain is called, the first one returning a non-None
    value is then returned.
    """
    def __init__(self, providers=None, conversion_func=None):
        """Initalize a ChainProvider.

        :type providers: list
        :param providers: The initial list of providers to check for values
            when invoked.

        :type conversion_func: None or callable
        :param conversion_func: If this value is None then it has no affect on
            the return type. Otherwise, it is treated as a function that will
            transform provided value.
        """
        if providers is None:
            providers = []
        self._providers = providers
        self._conversion_func = conversion_func

    def provide(self):
        """Provide the value from the first provider to return non-None.

        Each provider in the chain has its provide method called. The first
        one in the chain to return a non-None value is the returned from the
        ChainProvider. When no non-None value is found, None is returned.
        """
        for provider in self._providers:
            value = provider.provide()
            if value is not None:
                return self._convert_type(value)
        return None

    def _convert_type(self, value):
        if self._conversion_func is not None:
            return self._conversion_func(value)
        return value

    def __repr__(self):
        return '[%s]' % ', '.join([str(p) for p in self._providers])


class InstanceVarProvider(BaseProvider):
    """This class loads config values from the session instance vars."""
    def __init__(self, instance_var, session):
        """Initialize InstanceVarProvider.

        :type instance_var: str
        :param instance_var: The instance variable to load from the session.

        :type session: :class:`botocore.session.Session`
        :param session: The botocore session to get the loaded configuration
            file variables from.
        """
        self._instance_var = instance_var
        self._session = session

    def provide(self):
        """Provide a config value from the session instance vars."""
        instance_vars = self._session.instance_variables()
        value = instance_vars.get(self._instance_var)
        return value

    def __repr__(self):
        return 'InstanceVarProvider(instance_var=%s, session=%s)' % (
            self._instance_var,
            self._session,
        )


class ScopedConfigProvider(BaseProvider):
    def __init__(self, config_var_name, session):
        """Initialize ScopedConfigProvider.

        :type config_var_name: str
        :param config_var_name: The name of the config variable to load from
            the configuration file.

        :type session: :class:`botocore.session.Session`
        :param session: The botocore session to get the loaded configuration
            file variables from.
        """
        self._config_var_name = config_var_name
        self._session = session

    def provide(self):
        """Provide a value from a config file property."""
        config = self._session.get_scoped_config()
        value = config.get(self._config_var_name)
        return value

    def __repr__(self):
        return 'ScopedConfigProvider(config_var_name=%s, session=%s)' % (
            self._config_var_name,
            self._session,
        )


class EnvironmentProvider(BaseProvider):
    """This class loads config values from environment variables."""
    def __init__(self, names, env):
        """Initialize with the keys in the dictionary to check.

        :type names: str or list
        :param names: If this is a str, the key with that name will
            be loaded and returned. If this variable is
            a list, then it must be a list of str. The same process will be
            repeated for each string in the list, the first that returns non
            None will be returned.

        :type env: dict
        :param env: Environment variables dictionary to get variables from.
        """
        self._names = names
        self._env = env

    def provide(self):
        """Provide a config value from a source dictionary."""
        names = self._names
        if not isinstance(names, list):
            names = [names]
        for name in names:
            if name in self._env:
                return self._env[name]
        return None

    def __repr__(self):
        return 'EnvironmentProvider(names=%s, env=%s)' % (self._names,
                                                          self._env)


class ConstantProvider(BaseProvider):
    """This provider provides a constant value."""
    def __init__(self, value):
        self._value = value

    def provide(self):
        """Provide the constant value given during initialization."""
        return self._value

    def __repr__(self):
        return 'ConstantProvider(value=%s)' % self._value
