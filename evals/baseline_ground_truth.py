from __future__ import annotations

from copy import deepcopy
from typing import Any


BASELINE_INTERFACE_TO_OPERATION = {
    "SHOP-001": "get-shop-id",
    "SHOP-004": "get-shop-of-type",
    "SHOP-TYPE-001": "get-shop-type-list",
    "VOUCHER-002": "get-voucher-id",
    "BLOG-008": "get-blog-hot",
    "USER-004": "get-user-me",
    "BLOG-003": "get-blog-id",
    "SHOP-TYPE-002": "post-shop-type",
    "USER-008": "put-user-info",
    "SHOP-TYPE-004": "delete-shop-type-id",
}


def _assertion(
    assertion_id: str,
    assertion_type: str,
    *,
    path: str | None = None,
    operator: str | None = None,
    expected: Any = None,
    description: str | None = None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "assertion_id": assertion_id,
        "type": assertion_type,
        "required": True,
    }
    if path is not None:
        value["path"] = path
    if operator is not None:
        value["operator"] = operator
    if expected is not None:
        value["expected"] = expected
    if description is not None:
        value["description"] = description
    return value


def _point(
    point_id: str,
    description: str,
    category: str,
    *assertions: dict[str, Any],
    verification_mode: str = "response_assertion",
    observation_requirements: list[str] | None = None,
    preconditions: list[str] | None = None,
) -> dict[str, Any]:
    value = {
        "point_id": point_id,
        "description": description,
        "category": category,
        "required_assertions": list(assertions),
        "verification_mode": verification_mode,
    }
    if observation_requirements:
        value["observation_requirements"] = observation_requirements
    if preconditions:
        value["preconditions"] = preconditions
    return value


def _fixture(
    reference: str,
    kind: str,
    description: str,
    *,
    token: str | None = None,
    resolution: str = "manual_setup",
) -> dict[str, Any]:
    value = {
        "reference": reference,
        "kind": kind,
        "description": description,
        "resolution": resolution,
    }
    if token is not None:
        value["token"] = token
    return value


def _db_fixture(reference: str, token: str, description: str) -> dict[str, Any]:
    return _fixture(reference, "database", description, token=token, resolution="local_token")


def _manual_fixture(
    reference: str,
    description: str,
    *,
    kind: str = "state",
    resolution: str = "manual_setup",
) -> dict[str, Any]:
    return _fixture(reference, kind, description, resolution=resolution)


BASELINE_POINTS: dict[str, list[dict[str, Any]]] = {
    "SHOP-001": [
        _point(
            "SHOP-001-POSITIVE",
            "使用存在且大于0的商铺ID查询成功，返回商铺对象。",
            "positive",
            _assertion("SHOP-001-POSITIVE-STATUS", "status_code", operator="eq", expected=200),
            _assertion("SHOP-001-POSITIVE-SUCCESS", "json_value", path="$.success", expected=True),
            _assertion("SHOP-001-POSITIVE-DATA", "json_exists", path="$.data", expected=True),
            _assertion("SHOP-001-POSITIVE-ID", "json_type", path="$.data.id", expected="integer"),
            _assertion("SHOP-001-POSITIVE-NAME", "json_type", path="$.data.name", expected="string"),
            _assertion("SHOP-001-POSITIVE-TYPEID", "json_type", path="$.data.typeId", expected="integer"),
            _assertion("SHOP-001-POSITIVE-IMAGES", "json_type", path="$.data.images", expected="string"),
            _assertion("SHOP-001-POSITIVE-AREA", "json_type", path="$.data.area", expected="string"),
            _assertion("SHOP-001-POSITIVE-ADDRESS", "json_type", path="$.data.address", expected="string"),
            _assertion("SHOP-001-POSITIVE-X", "json_type", path="$.data.x", expected="number"),
            _assertion("SHOP-001-POSITIVE-Y", "json_type", path="$.data.y", expected="number"),
            _assertion("SHOP-001-POSITIVE-AVGPRICE", "json_type", path="$.data.avgPrice", expected="number"),
            _assertion("SHOP-001-POSITIVE-SOLD", "json_type", path="$.data.sold", expected="integer"),
            _assertion("SHOP-001-POSITIVE-COMMENTS", "json_type", path="$.data.comments", expected="integer"),
            _assertion("SHOP-001-POSITIVE-SCORE", "json_type", path="$.data.score", expected="number"),
            _assertion("SHOP-001-POSITIVE-OPENHOURS", "json_type", path="$.data.openHours", expected="string"),
            preconditions=["准备一条存在且ID大于0的商铺记录。"],
        ),
        _point(
            "SHOP-001-BOUNDARY-ID",
            "商铺ID为0或负数时返回文档约定的参数错误；路径参数缺失属于路由级边界，另行验收。",
            "boundary",
            _assertion("SHOP-001-BOUNDARY-STATUS", "status_code", operator="eq", expected=200),
            _assertion("SHOP-001-BOUNDARY-SUCCESS", "json_value", path="$.success", expected=False),
            _assertion(
                "SHOP-001-BOUNDARY-ERROR",
                "json_value",
                path="$.errorMsg",
                expected="shop id is invalid",
            ),
            preconditions=["准备可发送0和负数路径参数的请求。"],
        ),
        _point(
            "SHOP-001-BOUNDARY-MIN",
            "在准备了ID为1的存在商铺记录时，使用大于0约束的最小整数值查询成功。",
            "boundary",
            _assertion("SHOP-001-BOUNDARY-MIN-STATUS", "status_code", operator="eq", expected=200),
            _assertion("SHOP-001-BOUNDARY-MIN-SUCCESS", "json_value", path="$.success", expected=True),
            _assertion("SHOP-001-BOUNDARY-MIN-DATA", "json_exists", path="$.data", expected=True),
            preconditions=["仅在测试数据中存在ID为1的商铺记录时执行。"],
        ),
        _point(
            "SHOP-001-NEGATIVE-TYPE-MISMATCH",
            "路径参数为非数字字面量时应触发参数类型转换或校验失败；需求文档未规定具体HTTP状态码和响应体。",
            "negative",
            verification_mode="observation",
            observation_requirements=[
                "记录非数字ID的实际HTTP状态码和响应体，确认未产生success=true的业务成功结果，并据源码或运行结果补充稳定断言。"
            ],
            preconditions=["发送一个非数字路径参数，例如 abc。"],
        ),
        _point(
            "SHOP-001-NEGATIVE-NOT-FOUND",
            "商铺不存在时返回业务失败，而不是伪造成功数据。",
            "negative",
            _assertion("SHOP-001-NEGATIVE-STATUS", "status_code", operator="eq", expected=200),
            _assertion("SHOP-001-NEGATIVE-SUCCESS", "json_value", path="$.success", expected=False),
            _assertion(
                "SHOP-001-NEGATIVE-ERROR",
                "json_value",
                path="$.errorMsg",
                expected="shop not found",
            ),
            preconditions=["准备一个不存在且大于0的商铺ID。"],
        ),
        _point(
            "SHOP-001-CONTRACT-CACHE-MISS",
            "缓存未命中时查询 MySQL，并将商铺数据写入默认30分钟缓存。",
            "contract",
            verification_mode="observation",
            observation_requirements=["确认缓存未命中时发生一次数据库回源并写入30分钟缓存。"],
            preconditions=["缓存键不存在，且准备一条存在的商铺记录。"],
        ),
        _point(
            "SHOP-001-CONTRACT-CACHE-HIT",
            "缓存命中时直接返回缓存数据，响应契约与数据库数据一致。",
            "contract",
            verification_mode="observation",
            observation_requirements=["确认缓存命中时不重复访问数据库，且响应字段与数据库契约一致。"],
            preconditions=["缓存键已写入目标商铺数据，且准备对应的商铺记录。"],
        ),
        _point(
            "SHOP-001-CONTRACT-NULL-CACHE",
            "商铺不存在时使用空值缓存，重复查询不会持续访问数据库。",
            "contract",
            verification_mode="observation",
            observation_requirements=["确认不存在商铺的重复查询不会持续触发数据库访问。"],
            preconditions=["准备一个不存在的商铺ID，且该ID对应的空值缓存初始不存在。"],
        ),
    ],
    "SHOP-004": [
        _point(
            "SHOP-004-POSITIVE",
            "使用大于0的类型ID和有效页码查询成功，返回商铺数组，每页最多5条；返回记录属于目标类型由独立观察点验证。",
            "positive",
            _assertion("SHOP-004-POSITIVE-SUCCESS", "json_value", path="$.success", expected=True),
            _assertion("SHOP-004-POSITIVE-DATA", "json_type", path="$.data", expected="array"),
            _assertion("SHOP-004-POSITIVE-PAGE-SIZE", "json_value", path="$.data.length", operator="<=", expected=5),
            preconditions=["准备一个存在的商铺类型ID和至少一页可返回的商铺记录。"],
        ),
        _point(
            "SHOP-004-CONTRACT-TYPE-FILTER",
            "返回的每条商铺记录都属于请求的 typeId。",
            "contract",
            verification_mode="observation",
            observation_requirements=["使用目标类型和另一类型的商铺数据，确认返回结果中的每条记录都属于请求的 typeId。"],
            preconditions=["准备目标类型下的商铺记录、另一类型的商铺记录，以及可核对记录类型的数据库或夹具数据。"],
        ),
        _point(
            "SHOP-004-BOUNDARY-TYPE-ID",
            "typeId 小于1时返回文档约定的参数错误。",
            "boundary",
            _assertion(
                "SHOP-004-BOUNDARY-TYPE-ERROR",
                "json_value",
                path="$.errorMsg",
                expected="typeId must be greater than 0",
            ),
            preconditions=["准备可发送0和负数 typeId 的请求。"],
        ),
        _point(
            "SHOP-004-BOUNDARY-CURRENT",
            "current 小于1时返回文档约定的参数错误。",
            "boundary",
            _assertion(
                "SHOP-004-BOUNDARY-CURRENT-ERROR",
                "json_value",
                path="$.errorMsg",
                expected="current must be greater than 0",
            ),
            preconditions=["准备一个存在的 typeId，以便只验证 current 参数边界。"],
        ),
        _point(
            "SHOP-004-NEGATIVE-TYPE-EMPTY",
            "类型ID不存在时返回空数组，不返回业务失败。",
            "negative",
            _assertion("SHOP-004-NEGATIVE-TYPE-DATA", "json_type", path="$.data", expected="array"),
            _assertion("SHOP-004-NEGATIVE-TYPE-EMPTY", "json_value", path="$.data.length", expected=0),
            preconditions=["准备一个不存在且大于0的 typeId。"],
        ),
        _point(
            "SHOP-004-BOUNDARY-PAGE-EMPTY",
            "页码超出数据范围时返回空数组。",
            "boundary",
            _assertion("SHOP-004-BOUNDARY-PAGE-DATA", "json_type", path="$.data", expected="array"),
            _assertion("SHOP-004-BOUNDARY-PAGE-EMPTY", "json_value", path="$.data.length", expected=0),
            preconditions=["准备一个有已知数据范围的 typeId，并使用明确超出最大页码的 current。"],
        ),
        _point(
            "SHOP-004-CONTRACT-ORDER",
            "结果按商铺ID升序，保证分页顺序稳定。",
            "contract",
            _assertion(
                "SHOP-004-CONTRACT-ORDER-ASSERTION",
                "json_array_sorted",
                path="$.data",
                expected={"fields": [{"path": "$.id", "order": "asc"}]},
            ),
            preconditions=["准备至少两条商铺记录，且按预期排序前的记录顺序可构造为非升序。"],
        ),
        _point(
            "SHOP-004-CONTRACT-METADATA",
            "响应不提供总数、总页数或 hasMore。",
            "contract",
            _assertion("SHOP-004-CONTRACT-NO-TOTAL", "json_exists", path="$.total", expected=False),
            _assertion("SHOP-004-CONTRACT-NO-TOTAL-PAGES", "json_exists", path="$.totalPages", expected=False),
            _assertion("SHOP-004-CONTRACT-NO-HAS-MORE", "json_exists", path="$.hasMore", expected=False),
        ),
        _point(
            "SHOP-004-CONTRACT-INVALID-PAGE-QUERY",
            "非法页码不得执行有效分页查询。",
            "contract",
            verification_mode="observation",
            observation_requirements=["确认 current 小于1时不会执行有效的数据库分页查询。"],
            preconditions=["准备可观察数据库或查询调用记录。"],
        ),
    ],
    "SHOP-TYPE-001": [
        _point(
            "SHOP-TYPE-001-POSITIVE",
            "公开查询商铺类型列表成功，返回商铺类型数组。",
            "positive",
            _assertion("SHOP-TYPE-001-POSITIVE-SUCCESS", "json_value", path="$.success", expected=True),
            _assertion("SHOP-TYPE-001-POSITIVE-DATA", "json_type", path="$.data", expected="array"),
            preconditions=["准备至少一条商铺类型记录。"],
        ),
        _point(
            "SHOP-TYPE-001-CONTRACT-SORT",
            "返回结果按 sort 升序排列。",
            "contract",
            _assertion(
                "SHOP-TYPE-001-CONTRACT-SORT-ASSERTION",
                "json_array_sorted",
                path="$.data",
                expected={"fields": [{"path": "$.sort", "order": "asc"}]},
            ),
            preconditions=["准备至少两条商铺类型记录，且按预期排序前的记录顺序可构造为非升序。"],
        ),
        _point(
            "SHOP-TYPE-001-CONTRACT-CACHE-STRUCTURE",
            "Redis 命中和 MySQL 查询的响应结构一致。",
            "contract",
            verification_mode="observation",
            observation_requirements=["分别验证缓存命中和缓存未命中时的响应结构一致。"],
            preconditions=["准备至少一条商铺类型记录，并能控制或清理 cache:shopType。"],
        ),
        _point(
            "SHOP-TYPE-001-CONTRACT-EMPTY",
            "数据库没有商铺类型记录时返回空数组。",
            "contract",
            _assertion("SHOP-TYPE-001-EMPTY-DATA", "json_type", path="$.data", expected="array"),
            _assertion("SHOP-TYPE-001-EMPTY-LENGTH", "json_value", path="$.data.length", expected=0),
            preconditions=["准备数据库中不存在商铺类型记录的空表状态，并清理 cache:shopType。"],
        ),
        _point(
            "SHOP-TYPE-001-CONTRACT-FIELDS",
            "响应中的第一条商铺类型记录不返回创建时间和更新时间。",
            "contract",
            _assertion("SHOP-TYPE-001-NO-CREATED", "json_exists", path="$.data[0].createTime", expected=False),
            _assertion("SHOP-TYPE-001-NO-UPDATED", "json_exists", path="$.data[0].updateTime", expected=False),
            preconditions=["至少存在一条商铺类型记录。"],
        ),
        _point(
            "SHOP-TYPE-001-CONTRACT-FIELDS-ALL",
            "响应中的每条商铺类型记录都不返回创建时间和更新时间。",
            "contract",
            verification_mode="observation",
            observation_requirements=["检查返回数组中的每条记录，确认均不包含 createTime 和 updateTime。"],
            preconditions=["准备至少两条商铺类型记录，并能逐条检查响应字段。"],
        ),
        _point(
            "SHOP-TYPE-001-CONTRACT-CACHE-LIFECYCLE",
            "当前缓存未配置TTL，数据变更时需要显式清理缓存。",
            "contract",
            verification_mode="observation",
            observation_requirements=["确认缓存没有TTL，并确认数据变更流程显式清理 cache:shopType。"],
            preconditions=["准备至少一条商铺类型记录，并能观察 Redis TTL 和缓存删除调用。"],
        ),
    ],
    "VOUCHER-002": [
        _point(
            "VOUCHER-002-POSITIVE",
            "使用存在且大于0的优惠券ID查询成功，返回优惠券基础信息。",
            "positive",
            _assertion("VOUCHER-002-POSITIVE-SUCCESS", "json_value", path="$.success", expected=True),
            _assertion("VOUCHER-002-POSITIVE-ID", "json_exists", path="$.data.id", expected=True),
            preconditions=["准备一张存在且ID大于0的优惠券。"],
        ),
        _point(
            "VOUCHER-002-BOUNDARY-ID",
            "优惠券ID为0或负数时返回文档约定的参数错误；路径参数缺失属于路由级边界，另行验收。",
            "boundary",
            _assertion(
                "VOUCHER-002-BOUNDARY-ERROR",
                "json_value",
                path="$.errorMsg",
                expected="voucherId is invalid",
            ),
            preconditions=["准备可发送0和负数路径参数的请求。"],
        ),
        _point(
            "VOUCHER-002-NEGATIVE-NOT-FOUND",
            "优惠券不存在时返回业务失败。",
            "negative",
            _assertion(
                "VOUCHER-002-NEGATIVE-ERROR",
                "json_value",
                path="$.errorMsg",
                expected="voucher not found",
            ),
            preconditions=["准备一个不存在且大于0的优惠券ID。"],
        ),
        _point(
            "VOUCHER-002-CONTRACT-NORMAL-FIELDS",
            "普通券不返回秒杀字段。",
            "contract",
            _assertion("VOUCHER-002-NORMAL-NO-STOCK", "json_exists", path="$.data.stock", expected=False),
            _assertion("VOUCHER-002-NORMAL-NO-BEGIN", "json_exists", path="$.data.beginTime", expected=False),
            _assertion("VOUCHER-002-NORMAL-NO-END", "json_exists", path="$.data.endTime", expected=False),
            preconditions=["准备一张普通券。"],
        ),
        _point(
            "VOUCHER-002-CONTRACT-SECKILL-FIELDS",
            "秒杀券返回 stock、beginTime、endTime。",
            "contract",
            _assertion("VOUCHER-002-SECKILL-STOCK", "json_exists", path="$.data.stock", expected=True),
            _assertion("VOUCHER-002-SECKILL-BEGIN", "json_exists", path="$.data.beginTime", expected=True),
            _assertion("VOUCHER-002-SECKILL-END", "json_exists", path="$.data.endTime", expected=True),
            preconditions=["准备一张秒杀券。"],
        ),
        _point(
            "VOUCHER-002-CONTRACT-STATUS",
            "下架和过期券仍可按ID查询，接口不限制优惠券状态。",
            "contract",
            verification_mode="observation",
            observation_requirements=["使用下架和过期数据验证接口仍可按ID返回详情。"],
            preconditions=["准备一张已下架券和一张已过期券。"],
        ),
    ],
    "BLOG-008": [
        _point(
            "BLOG-008-POSITIVE",
            "使用默认或有效页码查询热门笔记成功，返回笔记数组，每页最多10条。",
            "positive",
            _assertion("BLOG-008-POSITIVE-SUCCESS", "json_value", path="$.success", expected=True),
            _assertion("BLOG-008-POSITIVE-DATA", "json_type", path="$.data", expected="array"),
            _assertion("BLOG-008-POSITIVE-PAGE-SIZE", "json_value", path="$.data.length", operator="<=", expected=10),
            preconditions=["准备至少一条热门笔记，并准备一个默认或有效的 current。"],
        ),
        _point(
            "BLOG-008-BOUNDARY-CURRENT",
            "current 小于1时返回文档约定的参数错误。",
            "boundary",
            _assertion(
                "BLOG-008-BOUNDARY-ERROR",
                "json_value",
                path="$.errorMsg",
                expected="current must be greater than 0",
            ),
            preconditions=["准备可发送0和负数 current 的请求。"],
        ),
        _point(
            "BLOG-008-CONTRACT-SORT",
            "结果按 liked 降序排列，点赞数相同时按笔记ID降序。",
            "contract",
            _assertion(
                "BLOG-008-CONTRACT-SORT-ASSERTION",
                "json_array_sorted",
                path="$.data",
                expected={
                    "fields": [
                        {"path": "$.liked", "order": "desc"},
                        {"path": "$.id", "order": "desc"},
                    ]
                },
            ),
            preconditions=["结果至少包含两条热门笔记，且至少存在同点赞数的笔记用于验证 tie-breaker。"],
        ),
        _point(
            "BLOG-008-CONTRACT-NO-TOTAL",
            "响应不提供总记录数。",
            "contract",
            _assertion("BLOG-008-CONTRACT-NO-TOTAL-ASSERTION", "json_exists", path="$.total", expected=False),
        ),
        _point(
            "BLOG-008-CONTRACT-ANONYMOUS-LIKE",
            "接口公开访问且Token可选；未登录时所有笔记 isLike=false。",
            "contract",
            verification_mode="observation",
            observation_requirements=["不携带Token访问有数据页，确认每条笔记 isLike=false。"],
            preconditions=["热门笔记列表至少有一条数据。"],
        ),
        _point(
            "BLOG-008-CONTRACT-AUTHENTICATED-LIKE",
            "已登录时返回当前用户真实点赞状态。",
            "contract",
            verification_mode="observation",
            observation_requirements=["使用已点赞和未点赞的用户数据，确认 isLike 与点赞集合一致。"],
            preconditions=["准备已点赞和未点赞的用户状态，且热门笔记列表至少有一条数据。"],
        ),
        _point(
            "BLOG-008-CONTRACT-EMPTY",
            "无数据页返回空数组。",
            "contract",
            _assertion("BLOG-008-CONTRACT-EMPTY-DATA", "json_type", path="$.data", expected="array"),
            _assertion("BLOG-008-CONTRACT-EMPTY-LENGTH", "json_value", path="$.data.length", expected=0),
            preconditions=["准备一个明确超出热门笔记数据范围的 current，或准备无热门笔记数据的测试状态。"],
        ),
    ],
    "USER-004": [
        _point(
            "USER-004-POSITIVE",
            "有效Token查询当前用户成功，返回与登录用户一致的用户摘要。",
            "positive",
            _assertion("USER-004-POSITIVE-SUCCESS", "json_value", path="$.success", expected=True),
            _assertion("USER-004-POSITIVE-ID", "json_exists", path="$.data.id", expected=True),
            _assertion("USER-004-POSITIVE-NICKNAME", "json_exists", path="$.data.nickName", expected=True),
            _assertion("USER-004-POSITIVE-ICON", "json_exists", path="$.data.icon", expected=True),
            preconditions=["准备一个有效Token及其对应的真实用户会话。"],
        ),
        _point(
            "USER-004-AUTH",
            "缺少、过期或不存在的Token时返回HTTP 401。",
            "auth",
            _assertion("USER-004-AUTH-STATUS", "status_code", expected=401),
        ),
        _point(
            "USER-004-CONTRACT-SENSITIVE",
            "响应不得包含 phone、password、创建时间等敏感或内部字段。",
            "contract",
            _assertion("USER-004-CONTRACT-PHONE", "json_exists", path="$.data.phone", expected=False),
            _assertion("USER-004-CONTRACT-PASSWORD", "json_exists", path="$.data.password", expected=False),
            _assertion("USER-004-CONTRACT-CREATED", "json_exists", path="$.data.createTime", expected=False),
            preconditions=["准备一个有效Token及其对应的真实用户会话。"],
        ),
        _point(
            "USER-004-CONTRACT-SESSION-SOURCE",
            "用户摘要来自当前Token对应的Redis会话，而不是每次重新查询数据库。",
            "contract",
            verification_mode="observation",
            observation_requirements=["准备当前Token对应的Redis会话并观察数据库调用，确认返回用户与会话一致且未发生不必要的用户表查询。"],
            preconditions=["准备有效Token、对应用户会话和可观察的数据库调用记录。"],
        ),
    ],
    "BLOG-003": [
        _point(
            "BLOG-003-POSITIVE",
            "公开查询存在的笔记成功，返回笔记基础字段、作者昵称和头像。",
            "positive",
            _assertion("BLOG-003-POSITIVE-SUCCESS", "json_value", path="$.success", expected=True),
            _assertion("BLOG-003-POSITIVE-AUTHOR", "json_exists", path="$.data.name", expected=True),
            _assertion("BLOG-003-POSITIVE-ICON", "json_exists", path="$.data.icon", expected=True),
            preconditions=["准备一条存在且ID大于0的笔记。"],
        ),
        _point(
            "BLOG-003-BOUNDARY-ID",
            "笔记ID非法时返回文档约定的参数错误。",
            "boundary",
            _assertion(
                "BLOG-003-BOUNDARY-ERROR",
                "json_value",
                path="$.errorMsg",
                expected="blogId is invalid",
            ),
            preconditions=["准备可发送0和负数笔记ID的请求。"],
        ),
        _point(
            "BLOG-003-NEGATIVE-NOT-FOUND",
            "笔记不存在时返回业务失败。",
            "negative",
            _assertion(
                "BLOG-003-NEGATIVE-ERROR",
                "json_value",
                path="$.errorMsg",
                expected="blog not found",
            ),
            preconditions=["准备一个不存在且大于0的笔记ID。"],
        ),
        _point(
            "BLOG-003-CONTRACT-ANONYMOUS-LIKE",
            "接口公开访问；未登录访问时 isLike=false。",
            "contract",
            verification_mode="observation",
            observation_requirements=["不携带Token访问存在笔记，确认 isLike=false。"],
            preconditions=["准备一条存在的笔记。"],
        ),
        _point(
            "BLOG-003-CONTRACT-AUTHENTICATED-LIKE",
            "携带有效Token时，根据Redis点赞集合返回当前用户真实 isLike 状态。",
            "contract",
            verification_mode="observation",
            observation_requirements=["使用已点赞和未点赞的用户数据，确认 isLike 与Redis点赞集合一致。"],
            preconditions=["准备一条存在的笔记，以及已点赞和未点赞的用户状态。"],
        ),
    ],
    "SHOP-TYPE-002": [
        _point(
            "SHOP-TYPE-002-POSITIVE",
            "携带有效Token和合法JSON请求体时创建商铺类型成功，返回创建后的数据。",
            "positive",
            _assertion("SHOP-TYPE-002-POSITIVE-SUCCESS", "json_value", path="$.success", expected=True),
            _assertion("SHOP-TYPE-002-POSITIVE-DATA", "json_type", path="$.data", expected="object"),
            preconditions=["准备有效Token、合法JSON请求体和不重复的 name。"],
        ),
        _point(
            "SHOP-TYPE-002-AUTH",
            "缺少或无效Token时拒绝创建。",
            "auth",
            _assertion("SHOP-TYPE-002-AUTH-STATUS", "status_code", expected=401),
        ),
        _point(
            "SHOP-TYPE-002-BOUNDARY-NAME",
            "name 超过32字符时请求失败。",
            "boundary",
            _assertion("SHOP-TYPE-002-BOUNDARY-NAME-SUCCESS", "json_value", path="$.success", expected=False),
            preconditions=["准备有效Token和其他合法字段，并提交超过32字符的 name。"],
        ),
        _point(
            "SHOP-TYPE-002-BOUNDARY-NAME-REQUIRED",
            "name 缺失时请求失败。",
            "boundary",
            _assertion("SHOP-TYPE-002-BOUNDARY-NAME-REQUIRED-SUCCESS", "json_value", path="$.success", expected=False),
            preconditions=["准备有效Token和其他合法字段，并省略 name。"],
        ),
        _point(
            "SHOP-TYPE-002-BOUNDARY-ICON",
            "icon 超过255字符时请求失败。",
            "boundary",
            _assertion("SHOP-TYPE-002-BOUNDARY-ICON-SUCCESS", "json_value", path="$.success", expected=False),
            preconditions=["准备有效Token、合法 name 和超过255字符的 icon。"],
        ),
        _point(
            "SHOP-TYPE-002-BOUNDARY-SORT",
            "sort 小于0时请求失败。",
            "boundary",
            _assertion("SHOP-TYPE-002-BOUNDARY-SORT-SUCCESS", "json_value", path="$.success", expected=False),
            preconditions=["准备有效Token、合法 name 和 sort=-1。"],
        ),
        _point(
            "SHOP-TYPE-002-CONTRACT-SORT-DEFAULT",
            "请求体缺省 sort 时按0处理。",
            "contract",
            verification_mode="observation",
            observation_requirements=["省略 sort 创建类型，确认保存结果按0处理。"],
            preconditions=["准备有效且不重复的 name，并省略 sort 字段。"],
        ),
        _point(
            "SHOP-TYPE-002-NEGATIVE-DUPLICATE",
            "类型名称重复时返回业务失败。",
            "negative",
            _assertion("SHOP-TYPE-002-NEGATIVE-DUPLICATE-SUCCESS", "json_value", path="$.success", expected=False),
            preconditions=["准备有效Token，以及数据库中已经存在的类型名称。"],
        ),
        _point(
            "SHOP-TYPE-002-NEGATIVE-SAVE",
            "数据库保存失败时返回业务失败。",
            "negative",
            _assertion("SHOP-TYPE-002-NEGATIVE-SAVE-SUCCESS", "json_value", path="$.success", expected=False),
            preconditions=["准备有效创建请求，并配置可控的数据库保存失败注入或 Mock。"],
        ),
        _point(
            "SHOP-TYPE-002-CONTRACT-CACHE",
            "创建成功后清理商铺类型缓存。",
            "contract",
            verification_mode="observation",
            observation_requirements=["创建成功后确认 cache:shopType 被清理。"],
            preconditions=["准备有效的创建请求，并预先写入对应的 cache:shopType 缓存。"],
        ),
    ],
    "USER-008": [
        _point(
            "USER-008-POSITIVE",
            "有效Token和合法请求体更新当前用户详细资料成功。",
            "positive",
            _assertion("USER-008-POSITIVE-SUCCESS", "json_value", path="$.success", expected=True),
            preconditions=["准备有效Token和当前用户，以及符合字段长度限制的请求体。"],
        ),
        _point(
            "USER-008-AUTH",
            "缺少或无效Token时拒绝更新。",
            "auth",
            _assertion("USER-008-AUTH-STATUS", "status_code", expected=401),
        ),
        _point(
            "USER-008-BOUNDARY-REQUIRED",
            "请求体为空时返回 user info is required。",
            "boundary",
            _assertion(
                "USER-008-BOUNDARY-REQUIRED",
                "json_value",
                path="$.errorMsg",
                expected="user info is required",
            ),
            preconditions=["准备有效Token，并提交空请求体。"],
        ),
        _point(
            "USER-008-BOUNDARY-LENGTH-CITY",
            "city 超过64字符时返回 user info is too long。",
            "boundary",
            _assertion(
                "USER-008-BOUNDARY-LENGTH-CITY-ERROR",
                "json_value",
                path="$.errorMsg",
                expected="user info is too long",
            ),
            preconditions=["准备有效Token，并提交超过64字符的 city。"],
        ),
        _point(
            "USER-008-BOUNDARY-LENGTH-INTRODUCE",
            "introduce 超过128字符时返回 user info is too long。",
            "boundary",
            _assertion(
                "USER-008-BOUNDARY-LENGTH-INTRODUCE-ERROR",
                "json_value",
                path="$.errorMsg",
                expected="user info is too long",
            ),
            preconditions=["准备有效Token，并提交超过128字符的 introduce。"],
        ),
        _point(
            "USER-008-NEGATIVE-SAVE",
            "资料保存失败时返回 update user info failed。",
            "negative",
            _assertion(
                "USER-008-NEGATIVE-ERROR",
                "json_value",
                path="$.errorMsg",
                expected="update user info failed",
            ),
            preconditions=["准备有效Token和合法请求体，并配置可控的数据库保存失败注入或 Mock。"],
        ),
        _point(
            "USER-008-CONTRACT-CURRENT-USER",
            "只能修改当前登录用户，忽略请求中的 userId。",
            "contract",
            verification_mode="observation",
            observation_requirements=["伪造其他 userId 提交更新，确认不会修改其他用户。"],
            preconditions=["准备有效的当前用户Token、另一名用户和可修改的资料记录。"],
        ),
        _point(
            "USER-008-CONTRACT-PROTECTED-FIELDS",
            "客户端不能通过该接口直接修改 fans、followee、积分或等级。",
            "contract",
            verification_mode="observation",
            observation_requirements=["提交 userId、fans、followee、积分和等级字段，确认受保护字段不会被修改。"],
            preconditions=["准备当前用户及其可修改的资料记录，并记录更新前的受保护字段值。"],
        ),
        _point(
            "USER-008-CONTRACT-PRESERVE",
            "只提交部分字段时，未提交字段保持原值。",
            "contract",
            verification_mode="observation",
            observation_requirements=["只提交一个资料字段，确认其他字段保持原值。"],
            preconditions=["准备一条包含多个资料字段的现有用户资料记录。"],
        ),
        _point(
            "USER-008-CONTRACT-INITIALIZE",
            "资料记录不存在时创建记录，并初始化 fans=0、followee=0。",
            "contract",
            verification_mode="observation",
            observation_requirements=["对没有资料记录的用户首次更新，确认自动创建并初始化计数。"],
            preconditions=["准备有效用户，但其用户资料记录不存在。"],
        ),
    ],
    "SHOP-TYPE-004": [
        _point(
            "SHOP-TYPE-004-POSITIVE",
            "携带有效Token删除存在且未被商铺引用的商铺类型成功。",
            "positive",
            _assertion("SHOP-TYPE-004-POSITIVE-SUCCESS", "json_value", path="$.success", expected=True),
            preconditions=["准备有效Token、存在且未被商铺引用的商铺类型记录。"],
        ),
        _point(
            "SHOP-TYPE-004-AUTH",
            "缺少或无效Token时拒绝删除。",
            "auth",
            _assertion("SHOP-TYPE-004-AUTH-STATUS", "status_code", expected=401),
        ),
        _point(
            "SHOP-TYPE-004-BOUNDARY-ID",
            "ID非法时返回业务失败。",
            "boundary",
            _assertion("SHOP-TYPE-004-BOUNDARY-SUCCESS", "json_value", path="$.success", expected=False),
            preconditions=["准备可发送0、负数或非数字路径参数的请求，并确认其路由行为。"],
        ),
        _point(
            "SHOP-TYPE-004-NEGATIVE-NOT-FOUND",
            "类型不存在时返回业务失败。",
            "negative",
            _assertion("SHOP-TYPE-004-NOT-FOUND-SUCCESS", "json_value", path="$.success", expected=False),
            preconditions=["准备一个不存在且大于0的商铺类型ID。"],
        ),
        _point(
            "SHOP-TYPE-004-NEGATIVE-REFERENCED",
            "仍被商铺引用的类型禁止删除。",
            "negative",
            _assertion("SHOP-TYPE-004-REFERENCED-SUCCESS", "json_value", path="$.success", expected=False),
            preconditions=["准备一个仍被商铺记录引用的商铺类型。"],
        ),
        _point(
            "SHOP-TYPE-004-NEGATIVE-DELETE-FAILURE",
            "数据库删除失败时返回业务失败。",
            "negative",
            _assertion("SHOP-TYPE-004-DELETE-FAILURE-SUCCESS", "json_value", path="$.success", expected=False),
            preconditions=["准备可删除的商铺类型，并配置可控的数据库删除失败注入或 Mock。"],
        ),
        _point(
            "SHOP-TYPE-004-CONTRACT-CACHE",
            "删除成功后清理商铺类型缓存。",
            "contract",
            verification_mode="observation",
            observation_requirements=["删除成功后确认 cache:shopType 被清理。"],
            preconditions=["准备可删除的商铺类型记录，并预先写入对应的 cache:shopType 缓存。"],
        ),
    ],
}


BASELINE_FIXTURE_REQUIREMENTS: dict[str, list[dict[str, Any]]] = {
    "SHOP-001-POSITIVE": [
        _db_fixture(
            "existing-shop-id",
            "$DB_FIXTURE[existing:tb_shop:id]",
            "解析为一条存在的商铺ID。",
        )
    ],
    "SHOP-001-NEGATIVE-NOT-FOUND": [
        _db_fixture(
            "absent-shop-id",
            "$DB_FIXTURE[absent:tb_shop:id]",
            "解析为一个不存在的商铺ID。",
        )
    ],
    "SHOP-001-BOUNDARY-MIN": [
        _manual_fixture(
            "existing-shop-id-one",
            "仅在测试数据中确认存在ID为1的商铺记录。",
            kind="database",
        )
    ],
    "SHOP-001-NEGATIVE-TYPE-MISMATCH": [
        _manual_fixture(
            "manual:SHOP-001-NEGATIVE-TYPE-MISMATCH",
            "准备可发送非数字路径参数并记录实际响应。",
            kind="observation",
            resolution="manual_observation",
        )
    ],
    "SHOP-001-CONTRACT-CACHE-MISS": [
        _db_fixture(
            "existing-shop-id",
            "$DB_FIXTURE[existing:tb_shop:id]",
            "解析为一条存在的商铺ID。",
        ),
        _manual_fixture(
            "cache:shop:absent",
            "执行前清理目标商铺缓存键，确保缓存未命中。",
            kind="cache",
        ),
    ],
    "SHOP-001-CONTRACT-CACHE-HIT": [
        _db_fixture(
            "existing-shop-id",
            "$DB_FIXTURE[existing:tb_shop:id]",
            "解析为一条存在的商铺ID。",
        ),
        _manual_fixture(
            "cache:shop:present",
            "执行前写入目标商铺缓存键，并记录缓存内容。",
            kind="cache",
        ),
    ],
    "SHOP-001-CONTRACT-NULL-CACHE": [
        _db_fixture(
            "absent-shop-id",
            "$DB_FIXTURE[absent:tb_shop:id]",
            "解析为一个不存在的商铺ID。",
        ),
        _manual_fixture(
            "cache:shop:null-value",
            "执行前确认目标空值缓存不存在，并在第一次请求后观察其建立。",
            kind="cache",
        ),
    ],
    "SHOP-004-POSITIVE": [
        _db_fixture(
            "existing-shop-type-id",
            "$DB_FIXTURE[existing:tb_shop_type:id]",
            "解析为一个存在的商铺类型ID。",
        )
    ],
    "SHOP-004-CONTRACT-TYPE-FILTER": [
        _db_fixture(
            "existing-shop-type-id",
            "$DB_FIXTURE[existing:tb_shop_type:id]",
            "解析为一个存在的商铺类型ID。",
        ),
        _manual_fixture(
            "state:shop-type-filter-data",
            "准备目标类型和另一类型的商铺记录，供结果归属核对。",
        ),
    ],
    "SHOP-004-BOUNDARY-CURRENT": [
        _db_fixture(
            "existing-shop-type-id",
            "$DB_FIXTURE[existing:tb_shop_type:id]",
            "解析为一个存在的商铺类型ID。",
        )
    ],
    "SHOP-004-NEGATIVE-TYPE-EMPTY": [
        _db_fixture(
            "absent-shop-type-id",
            "$DB_FIXTURE[absent:tb_shop_type:id]",
            "解析为一个不存在的商铺类型ID。",
        )
    ],
    "SHOP-004-BOUNDARY-PAGE-EMPTY": [
        _db_fixture(
            "existing-shop-type-id",
            "$DB_FIXTURE[existing:tb_shop_type:id]",
            "解析为一个存在的商铺类型ID。",
        ),
        _manual_fixture(
            "state:shop-page-range",
            "准备可确定最大页码的商铺数据，供构造超范围页码。",
        ),
    ],
    "SHOP-TYPE-001-CONTRACT-CACHE-STRUCTURE": [
        _manual_fixture(
            "cache:shop-type-hit-miss",
            "分别准备 cache:shopType 命中和未命中状态。",
            kind="cache",
        )
    ],
    "SHOP-TYPE-001-CONTRACT-EMPTY": [
        _manual_fixture(
            "database:shop-type-empty",
            "准备无商铺类型记录的数据库状态，并清理 cache:shopType。",
            kind="database",
        )
    ],
    "SHOP-TYPE-001-CONTRACT-FIELDS": [
        _manual_fixture(
            "state:shop-type-record",
            "准备至少一条商铺类型记录。",
        )
    ],
    "SHOP-TYPE-001-CONTRACT-FIELDS-ALL": [
        _manual_fixture(
            "state:shop-type-records",
            "准备至少两条商铺类型记录，并逐条检查响应字段。",
        )
    ],
    "SHOP-TYPE-001-CONTRACT-CACHE-LIFECYCLE": [
        _manual_fixture(
            "cache:shop-type-lifecycle",
            "准备可观察 Redis TTL 和 cache:shopType 删除调用的环境。",
            kind="cache",
            resolution="manual_observation",
        )
    ],
    "VOUCHER-002-POSITIVE": [
        _db_fixture(
            "existing-voucher-id",
            "$DB_FIXTURE[existing:tb_voucher:id]",
            "解析为一张存在的优惠券ID。",
        )
    ],
    "VOUCHER-002-NEGATIVE-NOT-FOUND": [
        _db_fixture(
            "absent-voucher-id",
            "$DB_FIXTURE[absent:tb_voucher:id]",
            "解析为一个不存在的优惠券ID。",
        )
    ],
    "VOUCHER-002-CONTRACT-NORMAL-FIELDS": [
        _manual_fixture(
            "state:normal-voucher",
            "准备只存在于优惠券基础表、没有秒杀扩展记录的普通券。",
            kind="database",
        )
    ],
    "VOUCHER-002-CONTRACT-SECKILL-FIELDS": [
        _manual_fixture(
            "state:seckill-voucher",
            "准备同时存在优惠券基础记录和秒杀扩展记录的秒杀券。",
            kind="database",
        )
    ],
    "VOUCHER-002-CONTRACT-STATUS": [
        _manual_fixture(
            "state:voucher-statuses",
            "准备一张已下架券和一张已过期券。",
            kind="database",
        )
    ],
    "BLOG-008-POSITIVE": [
        _manual_fixture(
            "state:hot-blog-page",
            "准备至少一条热门笔记及有效页码数据。",
            kind="database",
        )
    ],
    "BLOG-008-CONTRACT-SORT": [
        _manual_fixture(
            "state:hot-blog-sort",
            "准备点赞数不同且存在相同点赞数的热门笔记，并构造可验证排序的结果。",
            kind="database",
        )
    ],
    "BLOG-008-CONTRACT-ANONYMOUS-LIKE": [
        _manual_fixture(
            "state:anonymous-hot-blog",
            "准备有数据的热门笔记页，并以不带 Token 的方式访问。",
            kind="state",
        )
    ],
    "BLOG-008-CONTRACT-AUTHENTICATED-LIKE": [
        _manual_fixture(
            "state:authenticated-hot-blog-like",
            "准备当前用户已点赞和未点赞的热门笔记状态。",
            kind="state",
        ),
        _manual_fixture(
            "auth:valid-provider",
            "使用项目配置的 Auth Provider 注入有效凭据。",
            kind="auth",
        ),
    ],
    "BLOG-008-CONTRACT-EMPTY": [
        _manual_fixture(
            "state:hot-blog-empty-page",
            "准备明确超出热门笔记数据范围的页码或无热门笔记状态。",
            kind="database",
        )
    ],
    "USER-004-POSITIVE": [
        _manual_fixture(
            "auth:valid-provider",
            "使用项目配置的 Auth Provider 注入有效凭据。",
            kind="auth",
        )
    ],
    "USER-004-AUTH": [
        _fixture(
            "auth:nonexistent-token",
            "auth",
            "使用执行器在本地解析的不存在 Token。",
            token="$AUTH_FIXTURE[nonexistent:token]",
            resolution="local_token",
        )
    ],
    "USER-004-CONTRACT-SENSITIVE": [
        _manual_fixture(
            "auth:valid-provider",
            "使用项目配置的 Auth Provider 注入有效凭据。",
            kind="auth",
        )
    ],
    "USER-004-CONTRACT-SESSION-SOURCE": [
        _manual_fixture(
            "auth:session-source",
            "准备当前 Token 对应的 Redis 会话，并开放数据库调用观察。",
            kind="observation",
            resolution="manual_observation",
        )
    ],
    "BLOG-003-POSITIVE": [
        _db_fixture(
            "existing-blog-id",
            "$DB_FIXTURE[existing:tb_blog:id]",
            "解析为一条存在的笔记ID。",
        )
    ],
    "BLOG-003-NEGATIVE-NOT-FOUND": [
        _db_fixture(
            "absent-blog-id",
            "$DB_FIXTURE[absent:tb_blog:id]",
            "解析为一个不存在的笔记ID。",
        )
    ],
    "BLOG-003-CONTRACT-ANONYMOUS-LIKE": [
        _db_fixture(
            "existing-blog-id",
            "$DB_FIXTURE[existing:tb_blog:id]",
            "解析为一条存在的笔记ID。",
        )
    ],
    "BLOG-003-CONTRACT-AUTHENTICATED-LIKE": [
        _db_fixture(
            "existing-blog-id",
            "$DB_FIXTURE[existing:tb_blog:id]",
            "解析为一条存在的笔记ID。",
        ),
        _manual_fixture(
            "auth:blog-like-state",
            "准备有效凭据以及当前用户已点赞和未点赞的 Redis 状态。",
            kind="state",
        ),
    ],
    "SHOP-TYPE-002-POSITIVE": [
        _manual_fixture(
            "state:unique-shop-type-name",
            "准备不重复的商铺类型名称和合法 JSON 请求体。",
        ),
        _manual_fixture(
            "auth:valid-provider",
            "使用项目配置的 Auth Provider 注入有效凭据。",
            kind="auth",
        ),
    ],
    "SHOP-TYPE-002-AUTH": [
        _fixture(
            "auth:nonexistent-token",
            "auth",
            "使用执行器在本地解析的不存在 Token。",
            token="$AUTH_FIXTURE[nonexistent:token]",
            resolution="local_token",
        )
    ],
    "SHOP-TYPE-002-NEGATIVE-DUPLICATE": [
        _db_fixture(
            "duplicate-shop-type-name",
            "$DB_FIXTURE[duplicate:tb_shop_type:name]",
            "解析为数据库中已存在的重复商铺类型名称。",
        )
    ],
    "USER-008-POSITIVE": [
        _manual_fixture(
            "auth:valid-provider",
            "使用项目配置的 Auth Provider 注入有效凭据。",
            kind="auth",
        ),
        _manual_fixture(
            "state:user-profile",
            "准备当前用户和符合字段限制的资料请求。",
        ),
    ],
    "USER-008-AUTH": [
        _fixture(
            "auth:nonexistent-token",
            "auth",
            "使用执行器在本地解析的不存在 Token。",
            token="$AUTH_FIXTURE[nonexistent:token]",
            resolution="local_token",
        )
    ],
    "SHOP-TYPE-004-POSITIVE": [
        _db_fixture(
            "unreferenced-shop-type-id",
            "$DB_FIXTURE[unreferenced:tb_shop_type:id:tb_shop:type_id]",
            "解析为未被商铺引用、可删除的商铺类型ID。",
        ),
        _manual_fixture(
            "auth:valid-provider",
            "使用项目配置的 Auth Provider 注入有效凭据。",
            kind="auth",
        ),
    ],
    "SHOP-TYPE-004-AUTH": [
        _fixture(
            "auth:nonexistent-token",
            "auth",
            "使用执行器在本地解析的不存在 Token。",
            token="$AUTH_FIXTURE[nonexistent:token]",
            resolution="local_token",
        )
    ],
    "SHOP-TYPE-004-NEGATIVE-NOT-FOUND": [
        _db_fixture(
            "absent-shop-type-id",
            "$DB_FIXTURE[absent:tb_shop_type:id]",
            "解析为一个不存在的商铺类型ID。",
        )
    ],
    "SHOP-TYPE-004-NEGATIVE-REFERENCED": [
        _db_fixture(
            "referenced-shop-type-id",
            "$DB_FIXTURE[referenced:tb_shop_type:id:tb_shop:type_id]",
            "解析为仍被商铺引用的商铺类型ID。",
        )
    ],
}


def _attach_fixture_requirements() -> None:
    for points in BASELINE_POINTS.values():
        for point in points:
            requirements = BASELINE_FIXTURE_REQUIREMENTS.get(point["point_id"])
            if requirements is None and point.get("preconditions"):
                requirements = [
                    _manual_fixture(
                        f"manual:{point['point_id']}",
                        "；".join(point["preconditions"]),
                        kind="observation" if point.get("verification_mode") == "observation" else "state",
                        resolution=(
                            "manual_observation"
                            if point.get("verification_mode") == "observation"
                            else "manual_setup"
                        ),
                    )
                ]
            if requirements:
                point["fixture_requirements"] = deepcopy(requirements)


_attach_fixture_requirements()


def points_for_interface(interface_id: str) -> list[dict[str, Any]] | None:
    points = BASELINE_POINTS.get(interface_id)
    return deepcopy(points) if points is not None else None
