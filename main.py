from sqlalchemy import or_
from db_connect import session, Device, SwitchPort, UserProperties
from datetime import date, timedelta
from collections import defaultdict


def nested_dict(n, type_of):
    """
    Создает словарь заданной размерности и типа
    """
    if n == 1:
        return defaultdict(type_of)
    else:
        return defaultdict(lambda: nested_dict(n - 1, type_of))


def get_switches_from_db():
    """
    Возвращает список устройств удовлетворяющих фильтрующим условиям в виде словаря словарей.
    Итерируется по списку устройств и отфильтровывает лишнее
    Записывает предварительное базовое количество свободных абонентских портов
    За основу берем положение что у 10-портового коммутаторов два trunk и восемь access портов, trunk не учитывается
    """
    right_dev_dict = {}
    for device in session.query(Device).filter(
            Device.location_type == 'signal_center',
            Device.location_id is not None,
            or_(Device.port_count == 10, Device.port_count >= 24),
            or_(Device.switch_role == 'acc', Device.switch_role == 'gb')):

        if device.port_count == 10:
            free = 8
        else:
            free = 24

        right_dev_dict[device.id] = {
            'location_id': device.location_id,
            'switch_role': device.switch_role,
            'port_count': device.port_count,
            'used': 0,
            'free': free
        }
    return right_dev_dict


def get_port_state_from_db(devs):
    """
    Принимает словарь с отфильтрованными устройствами и производит подсчет используемых и неиспользуемых портов
    Исключает порты <24 | <8 если они задействованы не для клиентских устройств
    """
    def check_access_port(a, b):
        if a <= 8 and b == 10 or a <= 24 <= b:
            devs[dev]['free'] -= 1

    # Для каждого устройства...
    usr = nested_dict(2, int)
    for dev, val in devs.items():
        # Создать список пользователей
        if len(usr[val['location_id']]) == 0:
            usr[val['location_id']] = []
        devs[dev]['usr'] = []
        # Для каждого порта...
        for port in session.query(SwitchPort).filter(SwitchPort.device_id == dev):
            # Крутить нужные счетчики
            if port.binding_type == 'user':
                devs[dev]['used'] += 1
                devs[dev]['free'] -= 1
                usr[val['location_id']].append(int(port.binding_value))
            elif port.binding_type is not None:
                check_access_port(port.port_id, devs[dev]['port_count'])
        usr[val['location_id']] = list(set(usr[val['location_id']]))
    return devs, usr


def unite_switches_under_unit(switches):
    """
    Объединяет значения коммутаторов под одним ШКД
    """
    united = nested_dict(2, int)
    cleaned = nested_dict(1, int)
    for name, val in switches.items():
        if len(united[val['location_id']]) == 0:
            united[val['location_id']] = []
        if val['switch_role'] == 'gb':
            united[val['location_id']].append([val['used'], 0, val['free'], 0])
        else:
            united[val['location_id']].append([0, val['used'], 0, val['free']])
    for unit, vals in united.items():
        united[unit] = [sum(i) for i in zip(*vals)]
        cleaned[unit] = {
            'location_id': unit,
            'used_gb': united[unit][0],
            'used_100': united[unit][1],
            'free_gb': united[unit][2],
            'free_100': united[unit][3],
            'dead_ports': 0,
            'forecast_no_free_ports': 0
        }
    return cleaned


class Forecast:
    """
    Для удобства все методы производящие подсчеты прогноза объединены в класс
    """
    def __init__(self, units, u_users):
        self.units = units
        self.u_users = u_users
        self.age_threshold = date.today() - timedelta(days=180)
        self.segment_reg_date = date.today()
        self.db_data = session
        self.dead_user_count = 0
        self.user_growth = 0
        self.segment_status = True
        self.unit_num = int()
        self.user_list = []

    def process(self):
        """
        Руководит последовательностью действий:
        1. Итерируется по всем пользователям и вычисляет дату начала работы сегмента
        2. Итерируется по живым пользователям
        3. Итерируется по мертвым
        4. Строит прогноз
        """
        for unit_num, user_list in self.u_users.items():
            self.unit_num = unit_num
            self.user_list = user_list
            self.db_data = self.db_data.query(UserProperties).filter(UserProperties.uid.in_(self.user_list))
            self.segment_reg_date = date.today()
            self.dead_user_count = 0
            self.user_growth = 0
            self.segment_status = True  # True, если сегмет старый, False, если новый
            self.process()
            self.segment()
            self.alive_users()
            self.dead_users()
            self.forecast()

    def segment(self):
        """
        Итерируется по пользователям и выставляет дату начала работы сегмента по дате регистрации первого пользователя
        Если сегмент младше 180 суток, статус сегмента изменяется для корректной работы вычислений при прогнозе
        """
        for user in self.db_data:
            if user.reg_date and user.reg_date < self.segment_reg_date:
                self.segment_reg_date = user.reg_date
        if self.segment_reg_date > self.age_threshold:
            self.segment_status = False

    def alive_users(self):
        """
        Обрабатывает живых юзеров, крутит счетчики. Длинные условия обусловлены наличием в таблице
        пользователей с незаполннеными полями (reg_date). Такие пользователи не учитываются в рассчетах
        если сегмент старше 180 дней и учитываются, если сегмент младше
        """
        for user in self.db_data.filter(UserProperties.ext_status_good.is_(True)):
            self.usr.remove(user.uid)
            if user.reg_date:
                if (user.reg_date >= self.age_threshold and self.segment_status) or (not self.segment_status):
                    self.user_growth += 1
            else:
                if not self.segment_status:
                    self.user_growth += 1

    def dead_users(self):
        """
        Обрабатывает мертвых юзеров, крутит счетчики мертвых и отключившихся пользователей.
        Для пользователей с незаполннеными полями (ext_close_date), если даты нет считается что срок больше 90 дней
        """
        dead_threshold = date.today() - timedelta(days=90)
        for user in self.db_data.filter(UserProperties.ext_status_good.is_(False)):
            self.usr.remove(user.uid)
            if (user.ext_close_date and user.ext_close_date <= dead_threshold) or user.ext_close_date is None:
                self.dead_user_count += 1
                self.user_growth -= 1

    def forecast(self):
        """
        Строит прогноз ожижаемого наступления окончания свободных портов, записывает полученное значение
        в соответствующую графу. Для некоторых сегментов отсутствует корректная дата начала работы
        (reg_date всех пользователей пусты). В таком случае прогноз по портам равен '-1'
        """
        self.units[self.unit]['dead_ports'] = self.dead_user_count
        if self.user_growth > 0 and self.segment_reg_date != date.today():
            freeports = self.units[self.unit]['free_100'] + self.units[self.unit]['free_gb']
            if self.segment_status:
                growth_per_day = self.user_growth / 180
            else:
                diff = (date.today() - self.segment_reg_date)
                growth_per_day = self.user_growth / int(diff.days)
            deadline = freeports / growth_per_day
            self.units[self.unit]['forecast_no_free_ports'] = int(deadline)
        else:
            self.units[self.unit]['forecast_no_free_ports'] = -1

    def final(self):
        """
        Возвращает list of dicts по заданной в тз форме
        :return:
        """
        final = []
        for unit, data in self.units.items():
            final.append(data)
        print(final)


if __name__ == '__main__':
    devices, users = get_port_state_from_db(get_switches_from_db())
    clean = unite_switches_under_unit(devices)
    result = Forecast(clean, users)
    result.process()
    result.final()
