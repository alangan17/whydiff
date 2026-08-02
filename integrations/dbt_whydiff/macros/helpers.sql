{% macro key_list(alias, keys) -%}
  {%- for key in keys -%}
    {{ alias }}.{{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
  {%- endfor -%}
{%- endmacro %}

{% macro key_join(left_alias, right_alias, keys) -%}
  {%- for key in keys -%}
    {{ left_alias }}.{{ adapter.quote(key) }} is not distinct from {{ right_alias }}.{{ adapter.quote(key) }}{% if not loop.last %} and {% endif %}
  {%- endfor -%}
{%- endmacro %}

{% macro coalesced_keys(left_alias, right_alias, keys) -%}
  {%- for key in keys -%}
    coalesce(cast({{ left_alias }}.{{ adapter.quote(key) }} as {{ dbt.type_string() }}), cast({{ right_alias }}.{{ adapter.quote(key) }} as {{ dbt.type_string() }})) as {{ adapter.quote(key) }}{% if not loop.last %}, {% endif %}
  {%- endfor -%}
{%- endmacro %}

{% macro key_values(alias, keys) -%}
  {%- for key in keys -%}
    coalesce(cast({{ alias }}.{{ adapter.quote(key) }} as {{ dbt.type_string() }}), '<null>'){% if not loop.last %} || '|' || {% endif %}
  {%- endfor -%}
{%- endmacro %}
