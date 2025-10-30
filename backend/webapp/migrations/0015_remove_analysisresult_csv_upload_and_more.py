from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ("webapp", "0014_factorsharedstats_enet_alpha_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # Remove fields only in migration state (no SQL against missing tables)
            state_operations=[
                migrations.RemoveField(model_name="analysisresult", name="csv_upload"),
                migrations.RemoveField(model_name="analysisresult", name="user"),
                migrations.RemoveField(model_name="backtestresult", name="analysis_result"),
                migrations.RemoveField(model_name="meanreversionresult", name="analysis_result"),
                migrations.RemoveField(model_name="betaforecastresult", name="analysis_result"),
                migrations.AlterUniqueTogether(name="backtestresult", unique_together=None),
                migrations.AlterUniqueTogether(name="betaforecastresult", unique_together=None),
                migrations.AlterUniqueTogether(name="meanreversionresult", unique_together=None),
                migrations.DeleteModel(name="ForecastResult"),
                migrations.DeleteModel(name="BacktestResult"),
                migrations.DeleteModel(name="MeanReversionResult"),
                migrations.DeleteModel(name="AnalysisResult"),
                migrations.DeleteModel(name="BetaForecastResult"),
            ],
            database_operations=[],
        ),
    ]
