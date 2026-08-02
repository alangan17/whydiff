{% macro compare_key_coverage(left_relation, right_relation, keys) %}
with whydiff_left_keys as (
  select {{ whydiff.key_list('source', keys) }}, count(*) as whydiff_row_count
  from {{ left_relation }} as source
  group by {{ whydiff.key_list('source', keys) }}
),
whydiff_right_keys as (
  select {{ whydiff.key_list('source', keys) }}, count(*) as whydiff_row_count
  from {{ right_relation }} as source
  group by {{ whydiff.key_list('source', keys) }}
)
select
  {{ whydiff.coalesced_keys('left_keys', 'right_keys', keys) }},
  coalesce(left_keys.whydiff_row_count, 0) as left_row_count,
  coalesce(right_keys.whydiff_row_count, 0) as right_row_count,
  case
    when coalesce(left_keys.whydiff_row_count, 0) > 1
      or coalesce(right_keys.whydiff_row_count, 0) > 1 then 'duplicate_key'
    when left_keys.whydiff_row_count is null then 'right_only'
    when right_keys.whydiff_row_count is null then 'left_only'
    else 'matched'
  end as classification
from whydiff_left_keys as left_keys
full outer join whydiff_right_keys as right_keys
  on {{ whydiff.key_join('left_keys', 'right_keys', keys) }}
{% endmacro %}
