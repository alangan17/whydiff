{% test reconciliation(model, compare_model, unique_key, measures=[]) %}
with whydiff_coverage as (
  {{ whydiff.compare_key_coverage(model, compare_model, unique_key) }}
),
whydiff_key_failures as (
  select
    case when classification = 'duplicate_key' then 'duplicate_keys' else 'missing_keys' end as finding_code,
    classification as finding_side,
    {{ whydiff.key_values('coverage', unique_key) }} as key_values,
    cast(null as {{ dbt.type_string() }}) as measure_name,
    cast(null as {{ dbt.type_numeric() }}) as left_value,
    cast(null as {{ dbt.type_numeric() }}) as right_value,
    cast(null as {{ dbt.type_numeric() }}) as difference
  from whydiff_coverage as coverage
  where classification <> 'matched'
)
{% if measures | length > 0 %},
whydiff_measures as (
  {{ whydiff.compare_measures(model, compare_model, unique_key, measures) }}
),
whydiff_measure_failures as (
  select
    'numeric_mismatch' as finding_code,
    classification as finding_side,
    {{ whydiff.key_values('measure_rows', unique_key) }} as key_values,
    measure_name,
    cast(left_value as {{ dbt.type_numeric() }}) as left_value,
    cast(right_value as {{ dbt.type_numeric() }}) as right_value,
    cast(difference as {{ dbt.type_numeric() }}) as difference
  from whydiff_measures as measure_rows
  where classification <> 'matched'
)
{% endif %}
select * from whydiff_key_failures
{% if measures | length > 0 %}
union all
select * from whydiff_measure_failures
{% endif %}
{% endtest %}
