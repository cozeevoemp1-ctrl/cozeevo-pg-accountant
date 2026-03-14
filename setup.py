from setuptools import setup, find_packages

setup(
    name="pg-accountant",
    version="1.0.0",
    description="AI-powered bookkeeping for PG businesses",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[],   # managed via requirements.txt
    entry_points={
        "console_scripts": [
            "ingest-file          = cli.ingest_file:ingest_file",
            "run-reconciliation   = cli.run_reconciliation:run_reconciliation",
            "generate-report      = cli.generate_report:generate_report",
            "start-api            = cli.start_api:start_api",
            "configure-workflow   = cli.configure_workflow:configure_workflow",
        ],
    },
)
