"""Model control syntax only; user/reference text is never rewritten.

Gemma 4 uses the Ollama think field. Existing model tags retain their legacy
Qwen soft switches until their own native adapters are validated.
"""
def uses_native_controls(model):
    return model.split(':', 1)[0].rsplit('/', 1)[-1].lower() == 'gemma4'


def system_instruction(template, model, reasoning):
    return template.removesuffix(' /no_think') if reasoning or uses_native_controls(model) else template


def user_instruction(content, model, reasoning):
    if uses_native_controls(model):
        return content
    return content + ('\n/think' if reasoning else '\n/no_think')
