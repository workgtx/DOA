from sqlalchemy import create_engine, MetaData, Table, Column
from sqlalchemy.orm import mapper, sessionmaker
from config import *


class Device(object):
    id = None
    type = None
    location_type = None
    location_id = None
    product_name = None
    port_count = None
    switch_role = None


class SwitchPort(object):
    uid = None
    device_id = None
    port_id = None
    binding_type = None
    binding_value = None


class UserProperties(object):
    uid = None
    reg_date = None
    ext_status_good = None
    ext_status_name = None
    ext_close_date = None


def load_db_session():
    """
    Функция загрузки новой сессии.
        В первом блоке кода производится подключение с необходимымы параметрами к заданной в config.py базе данных
        Во втором блоке кода с помощью параметра autoload производится загрузка структуры из табицы. Параметр
    primary_key принудельно указывается для таблиц, где в таблицах отсутствует первичный ключ (является нарушением
    первой нормальной формы)
        В третьем блоке кода отображаем таблицы в сответствующие классы, в структуре самих классов предуказаны
    значение необходимых полей, чтобы линтер не видел ошибки в структуре, при попытке вызова
    """
    db_engine = create_engine(f'mysql://{USER}:{PASSWORD}@{HOST}/{DB}')
    metadata = MetaData(db_engine)

    device_table = Table(
        'device', metadata,
        autoload=True)
    switch_table = Table(
        'switch_port', metadata,
        Column('device_id', primary_key=True),
        Column('port_id', primary_key=True),
        autoload=True)
    user_table = Table(
        'user_properties', metadata,
        Column('uid', primary_key=True),
        autoload=True)

    mapobjlist = [(Device, device_table), (SwitchPort, switch_table), (UserProperties, user_table)]
    [mapper(x, y) for x, y in mapobjlist]

    return sessionmaker(bind=db_engine)()


session = load_db_session()
