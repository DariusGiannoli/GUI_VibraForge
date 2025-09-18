# utils.py
"""
Utility functions for waveform generation and processing
"""

import ast
import numpy as np

def safe_eval_equation(expr: str, local_vars: dict) -> np.ndarray:
    """Safely evaluate a mathematical expression with restricted namespace."""
    if not isinstance(expr, str) or not expr.strip():
        raise ValueError("Equation is empty.")
    
    t = local_vars.get("t")
    f = local_vars.get("f")
    if t is None or f is None:
        raise ValueError("Missing required variables: t and f.")
    
    # Optional SciPy
    try:
        from scipy import signal as _sig
    except Exception:
        _sig = None
    
    # Define allowed functions and variables
    allowed = {
        "t": t, "f": f, 
        "A": local_vars.get("A", 1.0), 
        "phi": local_vars.get("phi", 0.0),
        "pi": np.pi, 
        "np": np,
        "sin": np.sin, "cos": np.cos, "tan": np.tan, 
        "exp": np.exp, "log": np.log,
        "sqrt": np.sqrt, "abs": np.abs, "clip": np.clip, 
        "arctan": np.arctan, "arcsin": np.arcsin, "arccos": np.arccos, 
        "sinh": np.sinh, "cosh": np.cosh, "tanh": np.tanh,
    }
    
    # Add SciPy functions if available
    if _sig is not None:
        allowed.update({"square": _sig.square, "sawtooth": _sig.sawtooth})
    
    # Parse and validate the expression
    node = ast.parse(expr, mode="eval")
    
    # Check for allowed constructs only
    for sub in ast.walk(node):
        if isinstance(sub, (
            ast.Expression, ast.Call, ast.Attribute, ast.Name, ast.Load,
            ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
            ast.Subscript, ast.Constant,
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
            ast.USub, ast.UAdd, ast.And, ast.Or, 
            ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
        )):
            continue
        raise ValueError("Disallowed construct in equation.")
    
    # Evaluate the expression
    y = eval(compile(node, "<equation>", "eval"), {"__builtins__": {}}, allowed)
    y = np.asarray(y, dtype=float)
    
    # Handle scalar results
    if y.ndim == 0:
        y = np.full_like(t, float(y), dtype=float)
    
    if y.ndim != 1:
        raise ValueError("Equation must produce a 1D vector.")
    
    # Handle size mismatch
    if y.size != t.size:
        if y.size == 1:
            y = np.full_like(t, float(y), dtype=float)
        else:
            raise ValueError("Signal length does not match time base.")
    
    # Check for invalid values
    if not np.isfinite(y).all():
        raise ValueError("Signal contains NaN/Inf.")
    
    return y

def normalize_signal(y: np.ndarray) -> np.ndarray:
    """Normalize signal to [-1, 1] range."""
    m = float(np.max(np.abs(y))) if y.size else 1.0
    return (y / m) if m > 1e-12 else y