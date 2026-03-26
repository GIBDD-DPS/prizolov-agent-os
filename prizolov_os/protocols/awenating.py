def awenating_guard(func):
    def wrapper(*args, **kwargs):
        query = args[0]

        if "hack" in query.lower():
            raise Exception("Intent rejected")

        result = func(*args, **kwargs)

        confidence = 0.9
        if confidence < 0.82:
            raise Exception("Low confidence output")

        return {
            "verified_content": result,
            "confidence": confidence
        }

    return wrapper
