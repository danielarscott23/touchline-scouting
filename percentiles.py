"""Display precision only; scoring always uses the original percentile."""
import math


def display_percentile(value):
    """Truncate to two decimal places so values below 100 never round to 100."""
    return math.floor(float(value)*100)/100
