# Contributing

Read the repository README for the metadata contract and validation commands.

For each pull request, describe:

- The intended result and whether an existing version changes.
- The FlowGraph version/backend used for your manual test.
- Required data, dependencies, network access, filesystem writes, external tools,
  and any embedded Python. Do not include private data or credentials.
- How a reviewer can reproduce the test and what output to expect.

Keep changes focused. Do not rename existing catalog keys or remove source mappings
casually; they will be needed to preserve existing database IDs during cutover.
Do not copy source IDs when adding versions. Changes to validation and CI require
the same scrutiny as executable application code.

Run the validator and its unit tests before opening a PR. A static validation pass
does not replace manual runtime testing or security review. Licensing and rights
to redistribute contributed workflows must be resolved with the repository owner.