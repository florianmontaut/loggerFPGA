# model/formula/errors.py
# (GLviewer : FormulaError hérite aussi de ressources.custom_exceptions.AnalysisError)


class FormulaError(ValueError):
    """Formule invalide (syntaxe, voie inconnue, erreur de calcul)."""
