import os
os.environ.setdefault('FLASK_CONFIG', 'development')
from app import create_app

app = create_app('development')

if __name__ == '__main__':
    uri = app.config['SQLALCHEMY_DATABASE_URI']
    assert uri.startswith('sqlite'), f'SAFETY ABORT: not sqlite -> {uri}'
    app.run(host='127.0.0.1', port=5050, debug=False, use_reloader=False)
