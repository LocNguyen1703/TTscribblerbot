from random import choice, randint

def get_response(user_input: str) -> str:
    lowered: str = user_input.lower()

    if lowered == '':
        return 'well, you\'re awfully silent...'
    elif 'hello' in lowered:
        return 'hello there!'
    elif 'how are you' in lowered:
        return 'Good, thanks!'
    elif 'bye' in lowered:
        return 'see you!'
    elif 'roll dice' in lowered:
        return f'you rolled: {randint(1, 6)}'
    else:
        return choice(['I do not understand',
                       'what are you talking about?',
                       'what kinda language is that?',
                       'would you mind repeating that?'])
