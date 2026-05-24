from app.services.code_prefix_entry_parser import parse_code_prefix_card


def parse_actor_search_card(text, href='', actor_name='', page_number=1):
    card = parse_code_prefix_card(
        text=text,
        href=href,
        prefix='',
        page_number=page_number,
    )
    return {
        'actor_name': str(actor_name or '').strip(),
        'code': card.get('code', ''),
        'title': card.get('title', ''),
        'author': '',
        'title_with_author': card.get('title_with_author', ''),
        'release_date': card.get('release_date', ''),
        'avfan_url': card.get('avfan_url', ''),
        'page_number': card.get('page_number', 1),
        'raw_text': card.get('raw_text', ''),
    }
