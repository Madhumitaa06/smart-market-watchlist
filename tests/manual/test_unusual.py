import anomaly

# Force the unusual path with synthetic moves against real history.
print("Big move, heavy volume:")
print(" ", anomaly.assess("RELIANCE.NS", 5.5, 40000000)["message"])

print("\nBig move, thin volume:")
print(" ", anomaly.assess("RELIANCE.NS", 5.5, 3000000)["message"])

print("\nBig drop:")
print(" ", anomaly.assess("TCS.NS", -6.0, 8000000)["message"])

print("\nUnknown ticker, no history:")
print(" ", anomaly.assess("NOHISTORY.NS", 3.0, 1000)["message"])
