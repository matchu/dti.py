from __future__ import annotations

import asyncio
from asyncio.queues import Queue
from typing import TYPE_CHECKING, Any, List, Optional, Sequence, Union

from .constants import (
    SEARCH_ITEM_IDS,
    SEARCH_QUERY,
    SEARCH_QUERY_EXACT_MULTIPLE,
    SEARCH_TO_FIT,
)
from .enums import ItemKind, LayerImageSize
from .errors import InvalidItemID
from .models import Item
from .state import State

if TYPE_CHECKING:
    from .types import ItemPayload


class DTISearch:
    # this is a base class
    def __init__(self, *, state: State, per_page: Optional[int] = None):
        self._state = state
        self._items: Queue[Optional[Item]] = Queue(maxsize=per_page or 0)
        self._exhausted = False

    async def fetch_items(self) -> List[ItemPayload]:
        raise NotImplementedError

    def post_fetch(self, items: Sequence[ItemPayload]):
        # override these where needed to do things like adding to offset
        # this here, by default, will exhaust the searcher, with single-offset searchers in mind
        self._exhausted = True

    async def _fill_items(self) -> None:
        items = await self.fetch_items()

        for item in items:
            if item:
                await self._items.put(Item(data=item, state=self._state))
            else:
                await self._items.put(None)

        self.post_fetch(items)

    def __aiter__(self):
        return self

    async def flatten(self) -> List[Item]:
        ret: List[Item] = []
        while True:
            try:
                item = await self.next()
                if item is None:
                    raise StopAsyncIteration
            except StopAsyncIteration:
                return ret
            else:
                ret.append(item)

    async def next(self) -> Optional[Item]:
        if self._items.empty() and not self._exhausted:
            await self._fill_items()

        try:
            return self._items.get_nowait()
        except asyncio.QueueEmpty:
            raise StopAsyncIteration

    async def __anext__(self):
        return await self.next()


class ItemIDSearch(DTISearch):
    # an item-ID search
    # TODO: might need to be tweaked to be paginated in the future
    def __init__(self, state: State, item_ids: Sequence[Union[str, int]]):
        super().__init__(state=state)
        self.item_ids = item_ids

    async def fetch_items(self) -> List[ItemPayload]:
        data = await self._state.http._query(  # type: ignore
            query=SEARCH_ITEM_IDS,
            variables={"itemIds": self.item_ids},
        )
        if data["data"]:
            return data["data"]["items"]
        raise InvalidItemID("An item ID that was searched is invalid.")


class PaginatedDTISearch(DTISearch):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.offset = 0
        self.per_page = 0

    async def fetch_items(self) -> List[ItemPayload]:
        raise NotImplementedError

    def post_fetch(self, items: Sequence[ItemPayload]):
        self.offset += self.per_page

        # when we find the last page, don't try another next time
        self._exhausted = len(items) < self.per_page


class ItemSearchToFit(PaginatedDTISearch):
    # a regular search query that fits the species/color given
    def __init__(
        self,
        *,
        query: str,
        species_id: int,
        color_id: int,
        per_page: int = 30,
        item_kind: Optional[ItemKind] = None,
        size: Optional[LayerImageSize] = None,
        state: State,
    ):
        super().__init__(state=state, per_page=per_page)
        self.query = query
        self.species_id = species_id
        self.color_id = color_id
        self.item_kind = item_kind
        self.offset = 0
        self.per_page = per_page
        self.size = size or LayerImageSize.SIZE_600

    async def fetch_items(self) -> List[ItemPayload]:
        data = await self._state.http._query(  # type: ignore
            query=SEARCH_TO_FIT,
            variables={
                "query": self.query,
                "speciesId": self.species_id,
                "colorId": self.color_id,
                "fitsPet": {"speciesId": self.species_id, "colorId": self.color_id},
                "itemKind": str(self.item_kind) if self.item_kind else None,
                "offset": self.offset,
                "limit": self.per_page,
                "size": str(self.size),
            },
        )
        return data["data"]["itemSearch"]["items"]


class ItemSearchNames(DTISearch):
    # an exact-match search for items
    # not-found items WILL yield None
    def __init__(
        self,
        *,
        state: State,
        names: Sequence[str],
    ):
        super().__init__(state=state)
        self.names = names

    async def fetch_items(self) -> List[ItemPayload]:
        data = await self._state.http._query(  # type: ignore
            query=SEARCH_QUERY_EXACT_MULTIPLE, variables={"names": self.names}
        )

        items: Union[ItemPayload, List[ItemPayload]] = data["data"]["itemsByName"]

        # ensure we're working with iterable lists of items
        # when we search for a single item, it returns just the item, so we pur it in a list
        if isinstance(items, list):
            return items
        return [items]


class ItemSearch(DTISearch):
    # a regular search query
    def __init__(
        self, *, state: State, query: str, item_kind: Optional[ItemKind] = None
    ):
        super().__init__(state=state)
        self.query = query
        self.item_kind = item_kind

    async def fetch_items(self) -> List[ItemPayload]:
        data = await self._state.http._query(  # type: ignore
            query=SEARCH_QUERY,
            variables={
                "query": self.query,
                "itemKind": str(self.item_kind) if self.item_kind else None,
            },
        )
        return data["data"]["itemSearch"]["items"]
