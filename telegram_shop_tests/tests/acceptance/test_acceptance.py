"""
Приёмочные тесты телеграм-бота.
Тесты А1-А12.

Проверяют пользовательские сценарии end-to-end.
"""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock
from app.services.catalog_service import CatalogService
from app.services.cart_service import CartService
from app.services.order_service import OrderService
from app.services.discount_service import DiscountService
from app.services.search_service import SearchService
from app.services.favorites_service import FavoritesService
from app.services.notification_service import NotificationService
from app.services.profile_service import ProfileService
from app.dto import ContactData, ProfileUpdate
from app.exceptions import InsufficientStockError, EmptyCartError
from tests.conftest import MockOrder


class TestAcceptance:

    @pytest.mark.asyncio
    async def test_a01_new_customer_full_journey(
        self, mock_product_repo, mock_cart_repo, mock_order_repo,
        mock_promocode_repo, mock_user_repo, mock_bot, test_products
    ):
        """А1: Полный путь нового покупателя: каталог → товар → корзина → заказ"""
        # Сервисы
        catalog_service = CatalogService(product_repo=mock_product_repo)
        cart_service = CartService(cart_repo=mock_cart_repo, product_repo=mock_product_repo)
        discount_service = DiscountService(promocode_repo=mock_promocode_repo)
        notification_service = NotificationService(bot=mock_bot, user_repo=mock_user_repo, config={})
        order_service = OrderService(
            order_repo=mock_order_repo, cart_service=cart_service, product_repo=mock_product_repo,
            discount_service=discount_service, notification_service=notification_service
        )
        
        user_id = 4  # Новый пользователь
        
        # 1. Просмотр каталога
        categories = await catalog_service.get_categories()
        assert len(categories) == 5
        
        # 2. Выбор категории
        products = await catalog_service.get_products_by_category(1)
        assert len(products) == 4
        
        # 3. Добавление в корзину
        await cart_service.add_item(user_id, product_id=3, qty=1)
        
        # 4. Проверка корзины
        cart = await cart_service.get_cart(user_id)
        assert not cart.is_empty
        
        # 5. Оформление заказа
        contact = ContactData(name="Новый", phone="+7 999 000-00-00", address="г. Москва, ул. Новая, д. 1, кв. 1")
        order = await order_service.create_order(user_id, contact, payment_method='card')
        
        assert order.status == 'created'
        assert order.total == Decimal('79990')

    @pytest.mark.asyncio
    async def test_a02_search_and_purchase(self, mock_product_repo, mock_cart_repo):
        """А2: Поиск товара и покупка: поиск 'айфон' → выбор → корзина"""
        search_service = SearchService(product_repo=mock_product_repo)
        cart_service = CartService(cart_repo=mock_cart_repo, product_repo=mock_product_repo)
        
        # 1. Поиск
        results = await search_service.search_products("айфон")
        assert len(results) > 0
        
        # 2. Добавление найденного товара
        iphone = next((r for r in results if r.product_id == 2), None)
        assert iphone is not None
        
        await cart_service.add_item(user_id=4, product_id=iphone.product_id, qty=1)
        
        # 3. Проверка корзины
        cart = await cart_service.get_cart(4)
        assert len(cart.items) == 1

    @pytest.mark.asyncio
    async def test_a03_purchase_with_promocode(self, mock_cart_repo, mock_product_repo, mock_promocode_repo):
        """А3: Покупка с промокодом SAVE10 применяет скидку 10%"""
        cart_service = CartService(cart_repo=mock_cart_repo, product_repo=mock_product_repo)
        discount_service = DiscountService(promocode_repo=mock_promocode_repo)
        
        # 1. Добавляем товар
        mock_cart_repo._data[4] = [
            {'product_id': 5, 'qty': 1, 'name': 'MacBook', 'price': Decimal('199990'), 'stock': 2, 'is_active': True}
        ]
        
        # 2. Применяем промокод
        cart = await cart_service.get_cart(4)
        result = await discount_service.apply_discounts(cart, "SAVE10")
        
        # 3. Проверяем скидку (10% от 199990 = 19999)
        assert result.promo_discount == Decimal('19999')

    @pytest.mark.asyncio
    async def test_a04_repeat_order(self, mock_user_repo, mock_order_repo, mock_cart_repo, mock_product_repo):
        """А4: Повторение предыдущего заказа заполняет корзину"""
        cart_service = CartService(cart_repo=mock_cart_repo, product_repo=mock_product_repo)
        profile_service = ProfileService(
            user_repo=mock_user_repo, order_repo=mock_order_repo, cart_service=cart_service
        )
        from tests.conftest import MockOrderItem
        mock_order_repo.get_order_items = AsyncMock(return_value=[
            MockOrderItem(1, 2, 3, "Samsung", Decimal('79990'), 1)
        ])
        
        # Повторяем заказ
        cart = await profile_service.repeat_order(user_id=1, order_id=2)
        
        assert cart is not None

    @pytest.mark.asyncio
    async def test_a05_favorites_to_cart(self, mock_favorites_repo, mock_product_repo, mock_cart_repo):
        """А5: Покупка из избранного: добавить в избранное → в корзину"""
        favorites_service = FavoritesService(favorites_repo=mock_favorites_repo, product_repo=mock_product_repo)
        cart_service = CartService(cart_repo=mock_cart_repo, product_repo=mock_product_repo)
        
        # 1. Добавляем в избранное
        await favorites_service.add_favorite(user_id=1, product_id=3)
        
        # 2. Получаем избранное
        favorites = await favorites_service.list_favorites(user_id=1)
        assert len(favorites) == 1
        
        # 3. Добавляем в корзину
        for product in favorites:
            await cart_service.add_item(user_id=1, product_id=product.id, qty=1)
        
        cart = await cart_service.get_cart(1)
        assert len(cart.items) == 1

    @pytest.mark.asyncio
    async def test_a06_update_profile(self, mock_user_repo, mock_order_repo):
        """А6: Обновление профиля сохраняет новые данные"""
        profile_service = ProfileService(user_repo=mock_user_repo, order_repo=mock_order_repo)
        
        profile = await profile_service.update_profile(user_id=1, data=ProfileUpdate(name="Новое Имя"))
        
        assert profile is not None

    @pytest.mark.asyncio
    async def test_a07_out_of_stock(self, mock_cart_repo, mock_product_repo, mock_bot):
        """А7: Попытка купить товар без остатка показывает ошибку"""
        cart_service = CartService(cart_repo=mock_cart_repo, product_repo=mock_product_repo)
        
        with pytest.raises(InsufficientStockError):
            await cart_service.add_item(user_id=4, product_id=1, qty=1)  # iPhone 15 Pro, stock=0

    @pytest.mark.asyncio
    async def test_a08_expired_promocode(self, mock_promocode_repo, mock_bot):
        """А8: Использование истёкшего промокода OLD показывает ошибку"""
        from datetime import datetime
        discount_service = DiscountService(promocode_repo=mock_promocode_repo)
        
        result = await discount_service.validate_promo("OLD", datetime.utcnow())
        
        assert result.valid == False
        assert "истёк" in result.error_message

    @pytest.mark.asyncio
    async def test_a09_empty_cart_checkout(self, mock_cart_repo, mock_order_repo, mock_product_repo):
        """А9: Оформление пустой корзины показывает ошибку"""
        cart_service = CartService(cart_repo=mock_cart_repo, product_repo=mock_product_repo)
        order_service = OrderService(order_repo=mock_order_repo, cart_service=cart_service)
        
        contact = ContactData(name="Тест", phone="+7 999 000-00-00", address="Адрес тестовый длинный")
        
        with pytest.raises(EmptyCartError):
            await order_service.create_order(user_id=4, contact=contact)

    @pytest.mark.asyncio
    async def test_a10_search_no_results(self, mock_product_repo, mock_bot):
        """А10: Поиск несуществующего товара возвращает пустой результат"""
        search_service = SearchService(product_repo=mock_product_repo)
        
        results = await search_service.search_products("xyznonexistent123")
        
        assert results == []

    @pytest.mark.asyncio
    async def test_a11_admin_receives_notification(self, mock_user_repo, mock_bot):
        """А11: Админ получает уведомление о новом заказе"""
        notification_service = NotificationService(
            bot=mock_bot, user_repo=mock_user_repo, config={'admin_ids': [100008, 100009]}
        )
        order = MockOrder(id=100, user_id=4, order_number="ORD-TEST-001", total=79990,
                         contact_name="Покупатель", contact_phone="+7 999 000-00-00")
        
        await notification_service.notify_admin_new_order(order)
        
        assert len(mock_bot.sent_messages) == 2
        admin_ids = {msg['chat_id'] for msg in mock_bot.sent_messages}
        assert 100008 in admin_ids
        assert 100009 in admin_ids

    @pytest.mark.asyncio
    async def test_a12_admin_updates_order_status(self, mock_order_repo, mock_user_repo, mock_bot):
        """А12: Админ меняет статус заказа → покупатель получает уведомление"""
        notification_service = NotificationService(bot=mock_bot, user_repo=mock_user_repo, config={})
        order_service = OrderService(order_repo=mock_order_repo, notification_service=notification_service)
        
        order = await order_service.update_status(order_id=2, status='shipped')
        
        assert order.status == 'shipped'
        assert len(mock_bot.sent_messages) >= 1
