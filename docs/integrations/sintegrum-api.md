# Sintegrum API 1.0
Rest API
Server: `https://api.sintegrum.com`
## Authorization
- `bearerAuth`: http / bearer, format `secret` -> header `Authorization: Bearer <secret>`

## Недокументовані поля, на які ми спираємось

Це вичитана копія їхнього swagger, і реальна відповідь ширша за схему. Перевірено
на живому фіді 17.08.2026 (`GET /external/{company}/course`):

| Поле | Що це |
|------|-------|
| `avatar_link` | ПУБЛІЧНЕ посилання на файл обкладинки (`https://fs1.sintegrum.com/api/v1/files/<token>`), JPEG ~1280x762, `Cache-Control: public, max-age=86400`, без авторизації. У схемі є лише `avatar_id`, а ендпоінта файлів немає взагалі -- без цього поля дістати картинку нічим |
| `background_link` | Те саме для фону; у всіх наших курсів `null` |
| `type_track`, `alias_src`, `sale_price`, `sale_status`, `currency`, `branch_id`, `requirement`, `responsibility`, `final_text`, `created_at` | Приходять, але ми їх не використовуємо; лежать у `remote_payload` |

Оскільку поля недокументовані, код читає їх захищено: обкладинка тягнеться
через `app/services/online_course_media.py`, і будь-який збій там лише пише
в лог, не зриваючи синхронізацію каталогу. Токен у посиланні змінюється при
заміні файлу -- саме тому ми запам'ятовуємо посилання (`card_avatar_src`), а не
`avatar_id`.

## Endpoints

### Branch

#### GET `/external/{company}/branch/list` -- List Branch
List branch

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |

Responses:

- **200** OK

  `application/json` -- array<Branch>

```json
[
  {
    "id": 0,
    "name": "London office",
    "status": "1"
  }
]
```

### Candidate

#### POST `/external/{company}/candidate` -- Create Candidate
Create candidate

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |

Request body (`application/json`, CandidateCreate):

```json
{
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "John",
  "last_name": "Smith",
  "status": 0,
  "language": "en"
}
```

Responses:

- **201** OK

  `application/json` -- Candidate

```json
{
  "id": 0,
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "John",
  "last_name": "Smith",
  "status": 0,
  "access": 0,
  "language": "en",
  "created_at": 0,
  "hired_by": 0,
  "hired_at": 0,
  "recovery_at": 0
}
```

#### GET `/external/{company}/candidate/{candidateId}` -- View Candidate
View candidate

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `candidateId` | path | string | yes | Candidate Id |

Responses:

- **200** Success

  `application/json` -- Candidate

```json
{
  "id": 0,
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "John",
  "last_name": "Smith",
  "status": 0,
  "access": 0,
  "language": "en",
  "created_at": 0,
  "hired_by": 0,
  "hired_at": 0,
  "recovery_at": 0
}
```

#### PUT `/external/{company}/candidate/{candidateId}` -- Update Candidate
Update candidate

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `candidateId` | path | string | yes | Candidate Id |

Request body (`application/json`, CandidateCreate):

```json
{
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "John",
  "last_name": "Smith",
  "status": 0,
  "language": "en"
}
```

Responses:

- **200** OK

  `application/json` -- Candidate

```json
{
  "id": 0,
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "John",
  "last_name": "Smith",
  "status": 0,
  "access": 0,
  "language": "en",
  "created_at": 0,
  "hired_by": 0,
  "hired_at": 0,
  "recovery_at": 0
}
```

#### DELETE `/external/{company}/candidate/{candidateId}` -- Archive Candidate
Archive candidate

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `candidateId` | path | string | yes | Candidate Id |

Responses:

- **204** OK

#### GET `/external/{company}/candidate/list` -- List Candidate
List candidate

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `page` | query | string | no | page result |
| `per-page` | query | string | no | page size result |
| `sort` | query | string | no | sort page result [full_name, first_name, salary_min, salary_max, last_visit, created_at, cv_status, mark_cv, mark_quiz, progress_percent, position_name, branch_name, -last_visit] |
| `filter` | query | string | no | filter result example filter[branches][in][0]=523; filter[departments][in][0]=2 |

Responses:

- **200** OK

  `application/json` -- array<Candidate>

```json
[
  {
    "id": 0,
    "email": "mail@gmail.com",
    "phone": "+380990000000",
    "first_name": "John",
    "last_name": "Smith",
    "status": 0,
    "access": 0,
    "language": "en",
    "created_at": 0,
    "hired_by": 0,
    "hired_at": 0,
    "recovery_at": 0
  }
]
```

### Config

#### GET `/external/{company}/config` -- Get Company Config
Get your company config

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |

Responses:

- **200** OK

### Course

#### GET `/external/{company}/course` -- List Course
List course

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `page` | query | string | no | page result |
| `per-page` | query | string | no | page size result |
| `sort` | query | string | no | sort page result [id, name, -id] |

Responses:

- **200** OK

  `application/json` -- array<Course>

```json
[
  {
    "id": 0,
    "name": "Sales training",
    "position_type_id": 0,
    "position_group_id": 0,
    "status": 0,
    "parent_id": 0,
    "description": "string",
    "description_vacancy": "string",
    "price": 0,
    "avatar_id": 0,
    "background_id": 0,
    "count_registration": 0,
    "created_by": 0
  }
]
```

### Department

#### GET `/external/{company}/department/list` -- List Departments
List your company departments

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |

Responses:

- **200** OK

  `application/json` -- array<Department>

```json
[
  {
    "id": 0,
    "name": "Accountant , Logistics",
    "status": "1"
  }
]
```

### Position

#### GET `/external/{company}/position` -- List Position
List position

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `page` | query | string | no | page result |
| `per-page` | query | string | no | page size result |
| `sort` | query | string | no | sort page result [id, name, -id] |

Responses:

- **200** OK

  `application/json` -- array<Position>

```json
[
  {
    "id": 0,
    "name": "Sales training",
    "position_type_id": 0,
    "position_group_id": 0,
    "status": 0,
    "parent_id": 0,
    "description": "string",
    "description_vacancy": "string",
    "avatar_id": 0,
    "background_id": 0,
    "count_registration": 0,
    "created_by": 0
  }
]
```

### Position Group

#### GET `/external/{company}/position-group/list` -- List Position Group
List position group

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |

Responses:

- **200** OK

  `application/json` -- array<PositionGroup>

```json
[
  {
    "id": 0,
    "name": "Section sales",
    "status": 0,
    "is_last_row": 0
  }
]
```

### Progress

#### GET `/external/{company}/progress/assigned/{userId}` -- Progress User Assigned
Progress user assigned

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `userId` | path | string | yes | User Id |

Responses:

- **200** OK

  `application/json` -- array<Progress>

```json
[
  {
    "user_id": 0,
    "position_id": 0,
    "status": 0,
    "created_at": 0,
    "percent": 0
  }
]
```

#### GET `/external/{company}/progress/finished/{userId}` -- Progress User Finished
Progress user finished

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `userId` | path | string | yes | User Id |

Responses:

- **200** OK

  `application/json` -- array<Progress>

```json
[
  {
    "user_id": 0,
    "position_id": 0,
    "status": 0,
    "created_at": 0,
    "percent": 0
  }
]
```

#### GET `/external/{company}/progress/in-progress/{userId}` -- Progress User in Progress
Progress user in progress

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `userId` | path | string | yes | User Id |

Responses:

- **200** OK

  `application/json` -- array<Progress>

```json
[
  {
    "user_id": 0,
    "position_id": 0,
    "status": 0,
    "created_at": 0,
    "percent": 0
  }
]
```

### Progress Item

#### GET `/external/{company}/progress-item/cv-list` -- List 3D Resume Item
List 3D resume item

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `page` | query | string | no | page result |
| `per-page` | query | string | no | page size result |
| `filter` | query | string | no | filter result example filter[branches][in][0]=523; filter[departments][in][0]=2 |

Responses:

- **200** OK

  `application/json` -- array<CvProgressItem>

```json
[
  {
    "id": 0,
    "user_id": 0,
    "position_id": 0,
    "status": 0,
    "finished_at": 0,
    "position_name": "string",
    "first_name": "string",
    "last_name": "string",
    "position_type_alias": "string",
    "branch": "string"
  }
]
```

#### GET `/external/{company}/progress-item/list` -- List Progress Item
List progress item

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `page` | query | string | no | page result |
| `per-page` | query | string | no | page size result |
| `filter` | query | string | no | filter result example filter[branches][in][0]=523; filter[departments][in][0]=2 |

Responses:

- **200** OK

  `application/json` -- array<ProgressItem>

```json
[
  {
    "id": 0,
    "user_id": 0,
    "position_id": 0,
    "status": 0,
    "finished_at": 0,
    "position_name": "string",
    "track_item_id": 0,
    "track_item_name": "string",
    "first_name": "string",
    "last_name": "string",
    "position_type_alias": "string",
    "branch": "string"
  }
]
```

### Statistic

#### GET `/external/{company}/statistic/index` -- Get Overall Company Statistic and Counters
Get overall company statistic and counters

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |

Responses:

- **200** OK

### Student

#### POST `/external/{company}/student` -- Create Student
Create student

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |

Request body (`application/json`, StudentCreate):

```json
{
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "John",
  "last_name": "Smith",
  "status": 0,
  "language": "en"
}
```

Responses:

- **201** OK

  `application/json` -- Student

```json
{
  "id": 0,
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "John",
  "last_name": "Smith",
  "status": 0,
  "access": 0,
  "language": "en",
  "created_at": 0,
  "hired_by": 0,
  "hired_at": 0,
  "recovery_at": 0
}
```

#### GET `/external/{company}/student/{studentId}` -- View Student
View student

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `studentId` | path | string | yes | Student Id |

Responses:

- **200** Success

  `application/json` -- Student

```json
{
  "id": 0,
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "John",
  "last_name": "Smith",
  "status": 0,
  "access": 0,
  "language": "en",
  "created_at": 0,
  "hired_by": 0,
  "hired_at": 0,
  "recovery_at": 0
}
```

#### PUT `/external/{company}/student/{studentId}` -- Update Student
Update student

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `studentId` | path | string | yes | Student Id |

Request body (`application/json`, StudentCreate):

```json
{
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "John",
  "last_name": "Smith",
  "status": 0,
  "language": "en"
}
```

Responses:

- **200** OK

  `application/json` -- Student

```json
{
  "id": 0,
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "John",
  "last_name": "Smith",
  "status": 0,
  "access": 0,
  "language": "en",
  "created_at": 0,
  "hired_by": 0,
  "hired_at": 0,
  "recovery_at": 0
}
```

#### DELETE `/external/{company}/student/{studentId}` -- Archive Student
Archive student

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `studentId` | path | string | yes | Student Id |

Responses:

- **204** OK

#### GET `/external/{company}/student/list` -- List Student
List student

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `page` | query | string | no | page result |
| `per-page` | query | string | no | page size result |
| `sort` | query | string | no | sort page result [full_name, first_name, salary_min, salary_max, last_visit, created_at, cv_status, mark_cv, mark_quiz, progress_percent, position_name, branch_name, -last_visit] |
| `filter` | query | string | no | filter result example filter[branches][in][0]=523; filter[departments][in][0]=2 |

Responses:

- **200** OK

  `application/json` -- array<Student>

```json
[
  {
    "id": 0,
    "email": "mail@gmail.com",
    "phone": "+380990000000",
    "first_name": "John",
    "last_name": "Smith",
    "status": 0,
    "access": 0,
    "language": "en",
    "created_at": 0,
    "hired_by": 0,
    "hired_at": 0,
    "recovery_at": 0
  }
]
```

### User

#### POST `/external/{company}/user` -- Create User
Create user

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |

Request body (`application/json`, UserCreate):

```json
{
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "string",
  "last_name": "string",
  "status": 0,
  "language": "string",
  "active_to": 0
}
```

Responses:

- **201** OK

  `application/json` -- User

```json
{
  "id": 0,
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "string",
  "last_name": "string",
  "status": 0,
  "access": 0,
  "created_at": 0,
  "language": "string",
  "hired_by": 0,
  "hired_at": 0,
  "recovery_at": 0,
  "active_to": 0
}
```

#### POST `/external/{company}/user/{userId}/branches/{branchId}` -- Create Branch User
Create branch user

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `userId` | path | string | yes | User Id |
| `branchId` | path | string | yes | Branch id |

Responses:

- **200** OK

#### DELETE `/external/{company}/user/{userId}/branches/{branchId}` -- Delete Branch User
Delete branch user

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `userId` | path | string | yes | User Id |
| `branchId` | path | string | yes | Branch id |

Responses:

- **200** OK

#### POST `/external/{company}/user/{userId}/departments/{departmentId}` -- Create Department User
Create department user

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `userId` | path | string | yes | User Id |
| `departmentId` | path | string | yes | Department id |

Responses:

- **200** OK

#### DELETE `/external/{company}/user/{userId}/departments/{departmentId}` -- Delete Department User
Delete department user

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `userId` | path | string | yes | User Id |
| `departmentId` | path | string | yes | Department id |

Responses:

- **200** OK

#### POST `/external/{company}/user/{userId}/positions/{positionId}` -- Create Position User
Create position user

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `userId` | path | string | yes | User Id |
| `positionId` | path | string | yes | Position Id |

Responses:

- **200** OK

#### DELETE `/external/{company}/user/{userId}/positions/{positionId}` -- Delete Position User
Delete position user

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `userId` | path | string | yes | User Id |
| `positionId` | path | string | yes | Position Id |

Responses:

- **200** OK

#### GET `/external/{company}/user/{userId}` -- View User
View user

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `userId` | path | string | yes | User Id |

Responses:

- **200** OK

  `application/json` -- User

```json
{
  "id": 0,
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "string",
  "last_name": "string",
  "status": 0,
  "access": 0,
  "created_at": 0,
  "language": "string",
  "hired_by": 0,
  "hired_at": 0,
  "recovery_at": 0,
  "active_to": 0
}
```

#### PUT `/external/{company}/user/{userId}` -- Update User
Update user

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `userId` | path | string | yes | User Id |

Request body (`application/json`, UserCreate):

```json
{
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "string",
  "last_name": "string",
  "status": 0,
  "language": "string",
  "active_to": 0
}
```

Responses:

- **200** OK

  `application/json` -- User

```json
{
  "id": 0,
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "string",
  "last_name": "string",
  "status": 0,
  "access": 0,
  "created_at": 0,
  "language": "string",
  "hired_by": 0,
  "hired_at": 0,
  "recovery_at": 0,
  "active_to": 0
}
```

#### DELETE `/external/{company}/user/{userId}` -- Archive User
Archive user

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `userId` | path | string | yes | User Id |

Responses:

- **204** OK

#### GET `/external/{company}/user/list` -- List User
List user

Parameters:

| Name | In | Type | Required | Description |
|---|---|---|---|---|
| `company` | path | string | yes | Your company's unique alias at sintegrum.com eg yourcompany.sintegrum.com |
| `page` | query | string | no | page result |
| `per-page` | query | string | no | page size result |
| `sort` | query | string | no | sort page result [full_name, first_name, email, last_visit, branch_name, health, position_name] |
| `filter` | query | string | no | filter result example filter[branches][in][0]=523; filter[departments][in][0]=2 |

Responses:

- **200** OK

  `application/json` -- array<User>

```json
[
  {
    "id": 0,
    "email": "mail@gmail.com",
    "phone": "+380990000000",
    "first_name": "string",
    "last_name": "string",
    "status": 0,
    "access": 0,
    "created_at": 0,
    "language": "string",
    "hired_by": 0,
    "hired_at": 0,
    "recovery_at": 0,
    "active_to": 0
  }
]
```

## Schemas

### Branch

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| `id` | integer |  |  | The branch id |
| `name` | string |  | `"London office"` | The branch name |
| `status` | integer |  | `"1"` | The branch status (0 - unactive, 1 - active) |

```json
{
  "id": 0,
  "name": "London office",
  "status": "1"
}
```

### Candidate

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| `id` | integer |  |  | The candidate id |
| `email` | string |  | `"mail@gmail.com"` | The candidate email |
| `phone` | string |  | `"+380990000000"` | The user phone |
| `first_name` | string |  | `"John"` | The candidate first name |
| `last_name` | string |  | `"Smith"` | The candidate last name |
| `status` | integer |  |  | The candidate status (0 -blocked, 1 - unconfirmed, 2- active, 3 - archive) |
| `access` | integer |  |  | The candidate access status |
| `language` | string |  | `"en"` | The candidate select language short key |
| `created_at` | integer |  |  | The candidate created date timestamp |
| `hired_by` | integer |  |  | The candidate hired by user id |
| `hired_at` | integer |  |  | The candidate hired date timestamp |
| `recovery_at` | integer |  |  | The candidate recovered date timestamp |

```json
{
  "id": 0,
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "John",
  "last_name": "Smith",
  "status": 0,
  "access": 0,
  "language": "en",
  "created_at": 0,
  "hired_by": 0,
  "hired_at": 0,
  "recovery_at": 0
}
```

### CandidateCreate

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| `email` | string |  | `"mail@gmail.com"` | The candidate email |
| `phone` | string |  | `"+380990000000"` | The student phone |
| `first_name` | string |  | `"John"` | The candidate first name |
| `last_name` | string |  | `"Smith"` | The candidate last name |
| `status` | integer |  |  | The candidate status (0 -blocked, 1 - unconfirmed, 2- active, 3 - archive) |
| `language` | string |  | `"en"` | The candidate select language short key |

```json
{
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "John",
  "last_name": "Smith",
  "status": 0,
  "language": "en"
}
```

### Course

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| `id` | integer |  |  | The position id |
| `name` | string |  | `"Sales training"` | The position name |
| `position_type_id` | integer |  |  | Identity postition type id |
| `position_group_id` | integer |  |  | Identity position group id |
| `status` | integer |  |  | The position status (0 - unactive, 1 - active, 2 - archive) |
| `parent_id` | integer |  |  | Identity relation position id |
| `description` | string |  |  | The position description |
| `description_vacancy` | string |  |  | The position description_vacancy for position recruiting |
| `price` | integer |  |  | Price value course |
| `avatar_id` | integer |  |  | Identity icon avatar with type avatar |
| `background_id` | integer |  |  | Identity icon avatar with type background |
| `count_registration` | integer |  |  | The position count_registration, count registration from link registration |
| `created_by` | integer |  |  | The user created by user id |

```json
{
  "id": 0,
  "name": "Sales training",
  "position_type_id": 0,
  "position_group_id": 0,
  "status": 0,
  "parent_id": 0,
  "description": "string",
  "description_vacancy": "string",
  "price": 0,
  "avatar_id": 0,
  "background_id": 0,
  "count_registration": 0,
  "created_by": 0
}
```

### CvProgressItem

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| `id` | integer |  |  | Progress item id |
| `user_id` | integer |  |  | Identity user id owner progress position |
| `position_id` | integer |  |  | Identity position id |
| `status` | integer |  |  | The cv progress status (0 - new, 1 - in process, 2 - like, 3 - dislike) |
| `finished_at` | integer |  |  | Unix timestamp when item was finished |
| `position_name` | string |  |  | Position name |
| `first_name` | string |  |  | User first name |
| `last_name` | string |  |  | User last name |
| `position_type_alias` | string |  |  | Position type alias |
| `branch` | string |  |  | Branch name list |

```json
{
  "id": 0,
  "user_id": 0,
  "position_id": 0,
  "status": 0,
  "finished_at": 0,
  "position_name": "string",
  "first_name": "string",
  "last_name": "string",
  "position_type_alias": "string",
  "branch": "string"
}
```

### Department

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| `id` | integer |  |  | The department id |
| `name` | string |  | `"Accountant , Logistics"` | The department name |
| `status` | integer |  | `"1"` | The department status (0 - unactive, 1 - active) |

```json
{
  "id": 0,
  "name": "Accountant , Logistics",
  "status": "1"
}
```

### Group

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| `id` | integer |  |  | The user group id |
| `name` | string |  | `"London office"` | The user group name |
| `status` | integer |  | `"1"` | The user group status (0 - unactive, 1 - active) |

```json
{
  "id": 0,
  "name": "London office",
  "status": "1"
}
```

### Position

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| `id` | integer |  |  | The position id |
| `name` | string |  | `"Sales training"` | The position name |
| `position_type_id` | integer |  |  | Identity postition type id |
| `position_group_id` | integer |  |  | Identity position group id |
| `status` | integer |  |  | The position status (0 - unactive, 1 - active, 2 - archive) |
| `parent_id` | integer |  |  | Identity relation position id |
| `description` | string |  |  | The position description |
| `description_vacancy` | string |  |  | The position description_vacancy for position recruiting |
| `avatar_id` | integer |  |  | Identity icon avatar with type avatar |
| `background_id` | integer |  |  | Identity icon avatar with type background |
| `count_registration` | integer |  |  | The position count_registration, count registration from link registration |
| `created_by` | integer |  |  | The user created by user id |

```json
{
  "id": 0,
  "name": "Sales training",
  "position_type_id": 0,
  "position_group_id": 0,
  "status": 0,
  "parent_id": 0,
  "description": "string",
  "description_vacancy": "string",
  "avatar_id": 0,
  "background_id": 0,
  "count_registration": 0,
  "created_by": 0
}
```

### PositionGroup

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| `id` | integer |  |  | The position group id |
| `name` | string |  | `"Section sales"` | The position group name |
| `status` | integer |  |  | The position group status (0 - unactive, 1 - active, 2 - archive) |
| `is_last_row` | integer |  |  | The position group in list (0-regular, 1-last row) |

```json
{
  "id": 0,
  "name": "Section sales",
  "status": 0,
  "is_last_row": 0
}
```

### Progress

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| `user_id` | integer |  |  | Identity user id owner progress position |
| `position_id` | integer |  |  | Identity position id |
| `status` | integer |  |  | The progress status (0 - assigned, 1 - in progress, 2 - approved, 3 - reject, 4 - cancel) |
| `created_at` | integer |  |  | The datetime created at |
| `percent` | integer |  |  | The progress percent |

```json
{
  "user_id": 0,
  "position_id": 0,
  "status": 0,
  "created_at": 0,
  "percent": 0
}
```

### ProgressItem

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| `id` | integer |  |  | Progress item id |
| `user_id` | integer |  |  | Identity user id owner progress position |
| `position_id` | integer |  |  | Identity position id |
| `status` | integer |  |  | The progress item status (0 - created, 1 - checking, 2 - approved, 3 - rejected, 4 - canceled) |
| `finished_at` | integer |  |  | Unix timestamp when item was finished |
| `position_name` | string |  |  | Position name |
| `track_item_id` | integer |  |  | Track item id |
| `track_item_name` | string |  |  | Track item name |
| `first_name` | string |  |  | User first name |
| `last_name` | string |  |  | User last name |
| `position_type_alias` | string |  |  | Position type alias |
| `branch` | string |  |  | Branch name list |

```json
{
  "id": 0,
  "user_id": 0,
  "position_id": 0,
  "status": 0,
  "finished_at": 0,
  "position_name": "string",
  "track_item_id": 0,
  "track_item_name": "string",
  "first_name": "string",
  "last_name": "string",
  "position_type_alias": "string",
  "branch": "string"
}
```

### Student

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| `id` | integer |  |  | The student id |
| `email` | string |  | `"mail@gmail.com"` | The student email |
| `phone` | string |  | `"+380990000000"` | The user phone |
| `first_name` | string |  | `"John"` | The student first name |
| `last_name` | string |  | `"Smith"` | The student last name |
| `status` | integer |  |  | The student status (0 -blocked, 1 - unconfirmed, 2- active, 3 - archive) |
| `access` | integer |  |  | The student access status |
| `language` | string |  | `"en"` | The student select language short key |
| `created_at` | integer |  |  | The student created date timestamp |
| `hired_by` | integer |  |  | The student hired by user id |
| `hired_at` | integer |  |  | The student hired date timestamp |
| `recovery_at` | integer |  |  | The student recovered date timestamp |

```json
{
  "id": 0,
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "John",
  "last_name": "Smith",
  "status": 0,
  "access": 0,
  "language": "en",
  "created_at": 0,
  "hired_by": 0,
  "hired_at": 0,
  "recovery_at": 0
}
```

### StudentCreate

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| `email` | string |  | `"mail@gmail.com"` | The student email |
| `phone` | string |  | `"+380990000000"` | The student phone |
| `first_name` | string |  | `"John"` | The student first name |
| `last_name` | string |  | `"Smith"` | The student last name |
| `status` | integer |  |  | The student status (0 -blocked, 1 - unconfirmed, 2- active, 3 - archive) |
| `language` | string |  | `"en"` | The student select language short key |

```json
{
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "John",
  "last_name": "Smith",
  "status": 0,
  "language": "en"
}
```

### User

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| `id` | integer |  |  | The user id |
| `email` | string |  | `"mail@gmail.com"` | The user email |
| `phone` | string |  | `"+380990000000"` | The user phone |
| `first_name` | string |  |  | The user first name |
| `last_name` | string |  |  | The user last name |
| `status` | integer |  |  | The user status (0 -blocked, 1 - unconfirmed, 2- active, 3 - archive) |
| `access` | integer |  |  | The user access status |
| `created_at` | integer |  |  | The user created date timestamp |
| `language` | string |  |  | The user select language short key |
| `hired_by` | integer |  |  | The user hired by user id |
| `hired_at` | integer |  |  | The user hired date timestamp |
| `recovery_at` | integer |  |  | The user recovered date timestamp |
| `active_to` | integer |  |  | The user active to date timestamp |

```json
{
  "id": 0,
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "string",
  "last_name": "string",
  "status": 0,
  "access": 0,
  "created_at": 0,
  "language": "string",
  "hired_by": 0,
  "hired_at": 0,
  "recovery_at": 0,
  "active_to": 0
}
```

### UserCreate

| Field | Type | Required | Example | Description |
|---|---|---|---|---|
| `email` | string |  | `"mail@gmail.com"` | The user email |
| `phone` | string |  | `"+380990000000"` | The user phone |
| `first_name` | string |  |  | The user first name |
| `last_name` | string |  |  | The user last name |
| `status` | integer |  |  | The user status (0 -blocked, 1 - unconfirmed, 2- active, 3 - archive) |
| `language` | string |  |  | The user select language short key |
| `active_to` | integer |  |  | The user active to date timestamp |

```json
{
  "email": "mail@gmail.com",
  "phone": "+380990000000",
  "first_name": "string",
  "last_name": "string",
  "status": 0,
  "language": "string",
  "active_to": 0
}
```
