Thanks for coming here! This page documents miscellaneous cross-cutting facts about the project.

**Testing**: see [the architecture file](ARCHITECTURE.md#testing).

**Common changes and how to test them**
Here are some pointers on how to make certain kinds of common changes.

- changing the presentation of the dashboard, but not the underlying data: just edit `dashboard.py`, test using the testing data (see above)

- add a new dashboard, simple case: all data is already present
Just edit `dashboard.py`, test using the testing data (see above).
Add a new variant to `Dashboard`, and to the dictionaries in `short_description`, `long_description` and `getIdTitle`.

- add new metadata to the aggregate json file. This is not difficult, but requires changes in multiple stages.
1. Edit `process.py`, change the `get_aggregate_data` function to extract the data you want.
Pay attention to the fact that there is "basic" and "full" PR info; not all information might be available in both files.
2. Run `process.py` locally to update the generated file; commit the changes (except for the changed time-stamp). This step is optional; you can also just push the previous step and let CI perform this update.
3. Once step 2 is complete, edit the definition of `AggregatePRInfo` in `dashboard.py` to include your new data field. Update `PLACEHOLDER_AGGREGATE_INFO` as well. Update `read_json_files` to parse this field as well.
Congratulations, now you have made some new metadata available to the dashboard processing. (For making use of this, see the previous bullet point for changing the dashboard.)