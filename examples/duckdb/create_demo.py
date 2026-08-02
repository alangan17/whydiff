"""Create reproducible exact-match and mismatch relations for the README."""

from pathlib import Path

import duckdb

database = Path(__file__).with_name("whydiff_demo.duckdb")
connection = duckdb.connect(str(database))
for name in ("expected", "exact_actual", "actual"):
    connection.execute(f"drop table if exists {name}")
connection.execute("create table expected(id integer, amount decimal(10,2))")
connection.execute("insert into expected values (1, 10.00), (2, 20.00), (4, 40.00)")
connection.execute("create table exact_actual as select * from expected")
connection.execute("create table actual as select * from expected where false")
connection.execute("insert into actual values (1, 10.00), (3, 30.00), (4, 41.00)")
connection.close()
print(database)
