{% macro compare_measures(left_relation, right_relation, keys, measures, null_equals_zero=false) %}
with whydiff_left_measures as (
  select
    {{ whydiff.key_list('source', keys) }},
    {% for measure in measures %}{{ measure.expression }} as {{ adapter.quote(measure.name) }}{% if not loop.last %}, {% endif %}{% endfor %}
  from {{ left_relation }} as source
  group by {{ whydiff.key_list('source', keys) }}
),
whydiff_right_measures as (
  select
    {{ whydiff.key_list('source', keys) }},
    {% for measure in measures %}{{ measure.expression }} as {{ adapter.quote(measure.name) }}{% if not loop.last %}, {% endif %}{% endfor %}
  from {{ right_relation }} as source
  group by {{ whydiff.key_list('source', keys) }}
),
whydiff_joined as (
  select
    {{ whydiff.coalesced_keys('left_measures', 'right_measures', keys) }},
    {% for measure in measures %}
      left_measures.{{ adapter.quote(measure.name) }} as left_{{ measure.name }},
      right_measures.{{ adapter.quote(measure.name) }} as right_{{ measure.name }}{% if not loop.last %}, {% endif %}
    {% endfor %}
  from whydiff_left_measures as left_measures
  inner join whydiff_right_measures as right_measures
    on {{ whydiff.key_join('left_measures', 'right_measures', keys) }}
)
{% for measure in measures %}
select
  {{ whydiff.key_list('joined', keys) }},
  '{{ measure.name }}' as measure_name,
  joined.left_{{ measure.name }} as left_value,
  joined.right_{{ measure.name }} as right_value,
  abs({% if null_equals_zero %}coalesce(joined.left_{{ measure.name }}, 0){% else %}joined.left_{{ measure.name }}{% endif %}
    - {% if null_equals_zero %}coalesce(joined.right_{{ measure.name }}, 0){% else %}joined.right_{{ measure.name }}{% endif %}) as difference,
  case
    when joined.left_{{ measure.name }} is null and joined.right_{{ measure.name }} is null then 'matched'
    when not {{ null_equals_zero }} and (joined.left_{{ measure.name }} is null or joined.right_{{ measure.name }} is null) then 'measure_mismatch'
    when abs(coalesce(joined.left_{{ measure.name }}, 0) - coalesce(joined.right_{{ measure.name }}, 0))
      <= greatest(
        {{ measure.get('absolute_tolerance', 0) }},
        {{ measure.get('relative_tolerance', 0) }} * greatest(abs(coalesce(joined.left_{{ measure.name }}, 0)), abs(coalesce(joined.right_{{ measure.name }}, 0)))
      ) then 'matched'
    else 'measure_mismatch'
  end as classification
from whydiff_joined as joined
{% if not loop.last %}union all{% endif %}
{% endfor %}
{% endmacro %}
