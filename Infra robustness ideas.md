## Robustness ideas for my infrastructure

- avoid push races/conflicts
  - unracying: fix the inherent race between the two workflows, as well as I can
  - make pushing more resilient: add automatic conflict resolution

- avoid web-hooks time-outs: make sure the more frequent polling doesn't break havoc
  - trigger these hooks often enough:
    whenever a force-push happens, CI finishes, a new commit is made, somebody comments, reviews or some label changes. Also for draft status changes;  cross-references are not important. (Compare the full list of change events.)
  - these hooks get added to a queue, right --- so no flooding of workers, I hope?!
  - are these batched? if one PR has a label removed, a comment made, and a commit pushed --- can we make it so the last request "within reason" wins? Or only new data is downloaded (somehow, without re-implementing everything)? Would be nice to not re-download the world *all the time*. The current polling frequency keeps this within reason, would be nice to not regress *too* hard.

- make sure to detect all PR updates: web-hooks should help
hack for CI completed: auto-add awaiting-CI on every new push --- gets removed once sth passes :-)

- auto-identify out-of-date data
  - improve the data integrity check, to check old CI results: done
  - improve data integrity check: make it detect force-pushes
  - switch to full paranoia mode: comparing the key data on all open PRs; *that* paranoia could suffice once a day or so (to only plug the remaining leaks) --- multi-layered approach
- automatically re-download out of date PRs: that works reasonably well. Remaining improvements are tracked separately.

- once "missing" PRs are downloaded successfully, remove them from the 'missing_prs.txt' file
This step is currently, erm, missing --- and can stall future automatic updates of that file.

- recover from time-outs or rate-limiting in re-downloading
   - avoid discarding up to two re-downloaded PRs if only one fails
   - avoid getting stuck in a loop of one PR blocking everything
    partial fix implement (shuffling PRs, so new PRs will still tend to this)
   => auto-classify re-downloaded PRs as stubborns also, perhaps after 5 attempts? delete once successful?

- auto-classify "missing" PRs as stubborn
   run a period clean-up job, perhaps once a day?
   if one detects broken data, delete the broken data and create a file broken-number-full-1.txt
  - if that file already exists, create a file ...-2.txt
  - if that one already exists, create a file ...-3.txt
  - if that one also exists, add to stubborn files.

small observations, might not be worth fixing yet
- if backfilling a "standard PR" fails, backfilling a stubborn PR is not attempted yet
=> could re-order these steps for bigger robustness
