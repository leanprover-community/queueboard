Thanks for coming here! This page documents miscellaneous cross-cutting facts about the project.

**Testing**: see [the architecture file](ARCHITECTURE.md#testing).

**Common changes and how to test them**
Here are some pointers on how to make certain kinds of common changes.


Adding **new metadata** to the aggregate json file.
This is not difficult, but requires changes in multiple stages.
1. Edit `process.py`, change the `get_aggregate_data` function to extract the data you want.
Pay attention to the fact that there is "basic" and "full" PR info; not all information might be available in both files.
2. Run `process.py` locally to update the generated file; commit the changes (except for the changed time-stamp). This step is optional; you can also just push the previous step and let CI perform this update.
3. Once step 2 is complete, edit the definition of `AggregatePRInfo` in `compute_dashboard_prs.py` to include your new data field. Update `PLACEHOLDER_AGGREGATE_INFO` accordingly, and adjust `parse_aggregate_file` as well.
4. Congratulations, now you have made some new metadata available to the dashboard processing. (For making use of this, see the next bullet points for changing the dashboard.)


Just changing the **generated webpages**: edit `dashboard.py`, test using the testing data (see above).
For more detailed advice on particular kinds of changes, read on.

- change which data is shown for each PR: ensure the data you need is present in `AggregatePRInfo` (see above); then edit `_compute_pr_entries` in `dashboard.py` as desired

- add a new dashboard:
  - if additional data needs to be added, first follow the step above.
  - add your new dashboard to `mathlib_dashboards.py`: add a new variant to the `Dashboard` enum, and to the dictionaries in `short_description`, `long_description` and `getIdTitle`
  - decide on which generated HTML page the dashboard should appear. If you're unsure, feel free to ask the maintainers for advice!
  - Edit the method in `dashboard.py` corresponding to the webpage you want to change, e.g. `write_review_queue_page` if you want to modify the contents of the review queue page.

- add a dashboard with "custom columns", i.e. some additional columns present:
`write_dashboard` writes out most generated tables, but allows little customisation. For additional control, use `_write_table_row` and `_write_table_header`; see `print_on_the_queue_page` for an example.
