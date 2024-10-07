Thanks for coming here! This page documents miscellaneous cross-cutting facts about the project.

**Testing**: see [the architecture file](ARCHITECTURE.md#testing).

**Common changes and how to test them**
Here are some pointers on how to make certain kinds of common changes.

- changing the presentation of the dashboard, but not the underlying data: just edit `dashboard.py`, test using the testing data (see above)

- add a new dashboard, simple case: all data is already present
Just edit `dashboard.py`, test using the testing data (see above).
Add a new variant to `Dashboard`, and to the dictionaries in `short_description`, `long_description` and `getIdTitle`.

- add a new dashboard, complex case: you need to add a new query to `dashboard.sh`
In this case, also make sure to
  - add your new .json file to the `json-files` variable (or intentionally skip this step),
  - make sure to update `EXPECTED_INPUT_FILES` in `dashboard.py` to mention this the new file
