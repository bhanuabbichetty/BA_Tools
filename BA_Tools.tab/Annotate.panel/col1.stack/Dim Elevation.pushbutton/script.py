from pyrevit import revit, DB, forms


def projected_box(element, view, right, up):
    box = element.get_BoundingBox(view)
    if not box:
        return None
    points = []
    for x in (box.Min.X, box.Max.X):
        for y in (box.Min.Y, box.Max.Y):
            for z in (box.Min.Z, box.Max.Z):
                point = DB.XYZ(x, y, z)
                points.append((point.DotProduct(right), point.DotProduct(up)))
    return (min(p[0] for p in points), max(p[0] for p in points),
            min(p[1] for p in points), max(p[1] for p in points))


def projected_wall_bounds(walls, view, right, up):
    points = []
    for wall in walls:
        box = wall.get_BoundingBox(view)
        if not box:
            continue
        for x in (box.Min.X, box.Max.X):
            for y in (box.Min.Y, box.Max.Y):
                for z in (box.Min.Z, box.Max.Z):
                    point = DB.XYZ(x, y, z)
                    points.append((point.DotProduct(right), point.DotProduct(up)))
    if not points:
        raise Exception("The visible wall has no usable bounding box.")
    return (min(p[0] for p in points), max(p[0] for p in points),
            min(p[1] for p in points), max(p[1] for p in points))


def wall_references(walls, view, right, up):
    options = DB.Options()
    options.ComputeReferences = True
    options.View = view
    horizontal_negative = []
    horizontal_positive = []
    vertical_negative = []
    vertical_positive = []

    for wall in walls:
        for obj in wall.get_Geometry(options):
            if isinstance(obj, DB.GeometryInstance):
                geometry = obj.GetInstanceGeometry()
            else:
                geometry = [obj]
            for item in geometry:
                if not isinstance(item, DB.Solid) or not item.Faces.Size:
                    continue
                for face in item.Faces:
                    if not isinstance(face, DB.PlanarFace) or not face.Reference:
                        continue
                    normal = face.FaceNormal.Normalize()
                    point = face.Origin
                    right_dot = normal.DotProduct(right)
                    up_dot = normal.DotProduct(up)
                    if right_dot < -0.98:
                        horizontal_negative.append((point.DotProduct(right), face.Reference))
                    elif right_dot > 0.98:
                        horizontal_positive.append((point.DotProduct(right), face.Reference))
                    if up_dot < -0.98:
                        vertical_negative.append((point.DotProduct(up), face.Reference))
                    elif up_dot > 0.98:
                        vertical_positive.append((point.DotProduct(up), face.Reference))

    if not horizontal_negative or not horizontal_positive:
        raise Exception("Could not find the wall's left and right dimension faces.")
    if not vertical_negative or not vertical_positive:
        raise Exception("Could not find the wall's top and bottom dimension faces.")

    horizontal_negative.sort(key=lambda item: item[0])
    horizontal_positive.sort(key=lambda item: item[0])
    vertical_negative.sort(key=lambda item: item[0])
    vertical_positive.sort(key=lambda item: item[0])
    return (horizontal_negative[0], horizontal_positive[-1],
            vertical_negative[0], vertical_positive[-1])


def aperture_loops(walls, view, right, up):
    options = DB.Options()
    options.ComputeReferences = True
    options.View = view
    found = {}
    view_direction = view.ViewDirection.Normalize()

    for wall in walls:
        for obj in wall.get_Geometry(options):
            geometry = obj.GetInstanceGeometry() if isinstance(obj, DB.GeometryInstance) else [obj]
            for item in geometry:
                if not isinstance(item, DB.Solid) or not item.Faces.Size:
                    continue
                for face in item.Faces:
                    if not isinstance(face, DB.PlanarFace):
                        continue
                    if abs(face.FaceNormal.Normalize().DotProduct(view_direction)) < 0.90:
                        continue
                    for loop in face.EdgeLoops:
                        edges = []
                        points = []
                        valid = True
                        for edge in loop:
                            curve = edge.AsCurve()
                            if not isinstance(curve, DB.Line) or not edge.Reference:
                                valid = False
                                break
                            a = curve.GetEndPoint(0)
                            b = curve.GetEndPoint(1)
                            edges.append((a, b, edge.Reference))
                            points.extend((a, b))
                        if not valid or len(edges) != 4:
                            continue
                        us = [point.DotProduct(right) for point in points]
                        vs = [point.DotProduct(up) for point in points]
                        bounds = (min(us), max(us), min(vs), max(vs))
                        if bounds[1] - bounds[0] < 0.10 or bounds[3] - bounds[2] < 0.10:
                            continue
                        left = right_edge = bottom = top = None
                        for a, b, reference in edges:
                            du = abs((b - a).DotProduct(right))
                            dv = abs((b - a).DotProduct(up))
                            if dv > du:
                                coordinate = ((a.DotProduct(right) + b.DotProduct(right)) * 0.5,
                                              reference)
                                if abs(coordinate[0] - bounds[0]) < 0.01:
                                    left = coordinate
                                elif abs(coordinate[0] - bounds[1]) < 0.01:
                                    right_edge = coordinate
                            elif du > dv:
                                coordinate = ((a.DotProduct(up) + b.DotProduct(up)) * 0.5,
                                              reference)
                                if abs(coordinate[0] - bounds[2]) < 0.01:
                                    bottom = coordinate
                                elif abs(coordinate[0] - bounds[3]) < 0.01:
                                    top = coordinate
                        if left and right_edge and bottom and top:
                            key = tuple(round(value, 3) for value in bounds)
                            if key not in found:
                                found[key] = {
                                    "bounds": bounds,
                                    "left": left[1], "right": right_edge[1],
                                    "bottom": bottom[1], "top": top[1]
                                }
    return list(found.values())


def stable_key(reference, doc):
    return reference.ConvertToStableRepresentation(doc)


def existing_reference_sets(doc, view, ignored_ids=None):
    found = []
    ignored_ids = ignored_ids or set()
    for dimension in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.Dimension).WhereElementIsNotElementType():
        if dimension.Id.IntegerValue in ignored_ids:
            continue
        try:
            keys = frozenset(stable_key(reference, doc) for reference in dimension.References)
            if keys:
                found.append(keys)
        except Exception:
            pass
    return found


def matching_existing_chain(doc, view, points, line):
    target_ids = set(item[1].ElementId.IntegerValue for item in points)
    boundary_ids = set()
    if points:
        boundary_ids.add(points[0][1].ElementId.IntegerValue)
        boundary_ids.add(points[-1][1].ElementId.IntegerValue)
    interior_ids = target_ids.difference(boundary_ids)
    target_count = len(points)
    axis = line.Direction.Normalize()
    perpendicular = view.UpDirection.Normalize() if abs(axis.DotProduct(view.RightDirection.Normalize())) > 0.99 else view.RightDirection.Normalize()
    position = line.Origin.DotProduct(perpendicular)
    partial_ids = set()
    for dimension in DB.FilteredElementCollector(doc, view.Id).OfClass(DB.Dimension).WhereElementIsNotElementType():
        try:
            dim_line = dimension.Curve
            if abs(dim_line.Direction.Normalize().DotProduct(axis)) < 0.99:
                continue
            if abs(dim_line.Origin.DotProduct(perpendicular) - position) > 0.10:
                continue
            references = list(dimension.References)
            dim_ids = set(reference.ElementId.IntegerValue for reference in references)
            if target_ids.issubset(dim_ids) and len(references) >= target_count:
                return True, partial_ids
            if (dim_ids and dim_ids.issubset(target_ids) and
                    dim_ids.intersection(interior_ids) and len(references) < target_count):
                partial_ids.add(dimension.Id.IntegerValue)
        except Exception:
            pass
    return False, partial_ids


def group_points(items, tolerance=0.35):
    items = sorted(items, key=lambda item: item[0])
    groups = []
    for item in items:
        if not groups or abs(item[0] - sum(value[0] for value in groups[-1]) / len(groups[-1])) > tolerance:
            groups.append([item])
        else:
            groups[-1].append(item)
    return groups


def unique_chain(points):
    points.sort(key=lambda item: item[0])
    unique = []
    for point in points:
        if not unique or abs(point[0] - unique[-1][0]) > 0.015:
            unique.append(point)
    return unique


def opening_dimensions(elements, loops, bottom_ref, bounds, point_at, base_offset, chain_step,
                       category_label, view, right, up, wall_left_ref, wall_right_ref, wall_top_ref):
    min_u, max_u, min_v, max_v = bounds
    horizontal_rows = []
    vertical_columns = []
    loop_tolerance = 0.10

    for element in elements:
        box = projected_box(element, view, right, up)
        if not box:
            continue
        family_name = element.Symbol.Family.Name.lower()
        if "ncp-void" in family_name or "void" in family_name:
            candidate = None
            for loop in loops:
                if max(abs(loop["bounds"][index] - box[index]) for index in range(4)) <= loop_tolerance:
                    candidate = loop
                    break
            if not candidate:
                continue
            left_ref, right_ref = candidate["left"], candidate["right"]
            bottom_edge, top_ref = candidate["bottom"], candidate["top"]
            opening_bounds = candidate["bounds"]
        else:
            try:
                left_refs = list(element.GetReferences(DB.FamilyInstanceReferenceType.Left))
                right_refs = list(element.GetReferences(DB.FamilyInstanceReferenceType.Right))
                top_refs = list(element.GetReferences(DB.FamilyInstanceReferenceType.Top))
                bottom_refs = list(element.GetReferences(DB.FamilyInstanceReferenceType.Bottom))
                transform = element.GetTransform()
                if not left_refs or not right_refs or not top_refs:
                    continue
                if transform.BasisX.Normalize().DotProduct(revit.active_view.RightDirection.Normalize()) >= 0:
                    left_ref, right_ref = left_refs[0], right_refs[0]
                else:
                    left_ref, right_ref = right_refs[0], left_refs[0]
                if transform.BasisY.Normalize().DotProduct(revit.active_view.UpDirection.Normalize()) >= 0:
                    top_ref = top_refs[0]
                    bottom_edge = bottom_refs[0] if bottom_refs else bottom_ref[1]
                else:
                    top_ref = bottom_refs[0] if bottom_refs else top_refs[0]
                    bottom_edge = top_refs[0] if bottom_refs else bottom_ref[1]
                opening_bounds = box
            except Exception:
                continue

        center_u = (opening_bounds[0] + opening_bounds[1]) * 0.5
        center_v = (opening_bounds[2] + opening_bounds[3]) * 0.5
        horizontal_rows.append((center_v, opening_bounds[0], left_ref))
        horizontal_rows.append((center_v, opening_bounds[1], right_ref))
        vertical_columns.append((center_u, opening_bounds[2], bottom_edge))
        vertical_columns.append((center_u, opening_bounds[3], top_ref))

    plans = []
    for row_index, row in enumerate(group_points(horizontal_rows)):
        points = unique_chain([(item[1], item[2]) for item in row] +
                              [(wall_left_ref[0], wall_left_ref[1]),
                               (wall_right_ref[0], wall_right_ref[1])])
        if len(points) < 2:
            continue
        row_bottom = min(item[0] for item in row)
        line_v = row_bottom - base_offset - row_index * chain_step
        line = DB.Line.CreateBound(point_at(points[0][0], line_v), point_at(points[-1][0], line_v))
        plans.append((category_label + " horizontal opening edges", points, line))

    for column_index, column in enumerate(group_points(vertical_columns)):
        points = unique_chain([(item[1], item[2]) for item in column] +
                              [(bottom_ref[0], bottom_ref[1]),
                               (wall_top_ref[0], wall_top_ref[1])])
        if len(points) < 2:
            continue
        column_right = max(item[0] for item in column)
        line_u = column_right + base_offset + column_index * chain_step
        line = DB.Line.CreateBound(point_at(line_u, points[0][0]), point_at(line_u, points[-1][0]))
        plans.append((category_label + " vertical opening edges", points, line))
    return plans


def structural_dimensions(elements, bounds, point_at, base_offset, chain_step,
                          left_ref, right_ref, bottom_ref, top_ref):
    min_u, max_u, min_v, max_v = bounds
    horizontal = []
    vertical = []
    for element in elements:
        if element.GetType().Name != "FamilyInstance":
            continue
        try:
            family_name = element.Symbol.Family.Name.lower()
        except Exception:
            continue
        # Structural connection chains are intended for grout tube instances only.
        # Loop connections, dowels and other structural components are intentionally skipped.
        if "tube" not in family_name or "loop" in family_name:
            continue
        location = element.Location
        if not location or location.GetType().Name != "LocationPoint":
            continue
        point = location.Point
        try:
            horizontal_refs = list(element.GetReferences(DB.FamilyInstanceReferenceType.CenterLeftRight))
            vertical_refs = list(element.GetReferences(DB.FamilyInstanceReferenceType.CenterFrontBack))
            u = point.DotProduct(revit.active_view.RightDirection.Normalize())
            v = point.DotProduct(revit.active_view.UpDirection.Normalize())
            transform = element.GetTransform()
            if (horizontal_refs and abs(transform.BasisX.Normalize().DotProduct(revit.active_view.RightDirection.Normalize())) > 0.95
                    and min_u - 0.25 <= u <= max_u + 0.25 and min_v - 0.25 <= v <= max_v + 0.25):
                horizontal.append((v, u, horizontal_refs[0]))
            if (vertical_refs and abs(transform.BasisY.Normalize().DotProduct(revit.active_view.UpDirection.Normalize())) > 0.95
                    and min_u - 0.25 <= u <= max_u + 0.25 and min_v - 0.25 <= v <= max_v + 0.25):
                vertical.append((u, v, vertical_refs[0]))
        except Exception:
            continue

    plans = []
    for row_index, row in enumerate(group_points(horizontal)):
        points = unique_chain([(item[1], item[2]) for item in row] +
                              [(left_ref[0], left_ref[1]), (right_ref[0], right_ref[1])])
        if len(points) < 2:
            continue
        line_v = min(item[0] for item in row) - base_offset - (row_index + 1) * chain_step
        line = DB.Line.CreateBound(point_at(points[0][0], line_v), point_at(points[-1][0], line_v))
        plans.append(("Structural connection horizontal centers", points, line))

    for column_index, column in enumerate(group_points(vertical)):
        points = unique_chain([(item[1], item[2]) for item in column] +
                              [(bottom_ref[0], bottom_ref[1]), (top_ref[0], top_ref[1])])
        if len(points) < 2:
            continue
        line_u = max(item[0] for item in column) + base_offset + (column_index + 1) * chain_step
        line = DB.Line.CreateBound(point_at(line_u, points[0][0]), point_at(line_u, points[-1][0]))
        plans.append(("Structural connection vertical centers", points, line))
    return plans


def door_window_dimension_plans(elements, bounds, point_at, base_offset, chain_step,
                                right, up, wall_bottom_ref, wall_top_ref,
                                wall_left_ref, wall_right_ref):
    min_u, max_u, min_v, max_v = bounds
    horizontal_points = []
    vertical_points = []
    for element in elements:
        box = projected_box(element, revit.active_view, right, up)
        if not box:
            continue
        try:
            left_refs = list(element.GetReferences(DB.FamilyInstanceReferenceType.Left))
            right_refs = list(element.GetReferences(DB.FamilyInstanceReferenceType.Right))
            top_refs = list(element.GetReferences(DB.FamilyInstanceReferenceType.Top))
            bottom_refs = list(element.GetReferences(DB.FamilyInstanceReferenceType.Bottom))
            transform = element.GetTransform()
            if not left_refs or not right_refs or not top_refs:
                continue
            if transform.BasisX.Normalize().DotProduct(right) >= 0:
                left_ref, right_ref = left_refs[0], right_refs[0]
            else:
                left_ref, right_ref = right_refs[0], left_refs[0]
            if transform.BasisY.Normalize().DotProduct(up) >= 0:
                top_ref = top_refs[0]
                bottom_ref = bottom_refs[0] if bottom_refs else wall_bottom_ref[1]
                bottom_coordinate = box[2] if bottom_refs else wall_bottom_ref[0]
            else:
                top_ref = bottom_refs[0] if bottom_refs else top_refs[0]
                bottom_ref = top_refs[0] if top_refs else wall_bottom_ref[1]
                bottom_coordinate = box[2] if top_refs else wall_bottom_ref[0]
            horizontal_points.extend([(box[0], left_ref), (box[1], right_ref)])
            if bottom_ref and top_ref:
                vertical_points.extend([(bottom_coordinate, bottom_ref), (box[3], top_ref)])
        except Exception:
            continue

    plans = []
    if not horizontal_points:
        return plans
    horizontal = unique_chain(horizontal_points +
                              [(wall_left_ref[0], wall_left_ref[1]),
                               (wall_right_ref[0], wall_right_ref[1])])
    if len(horizontal) >= 2:
        line_v = min_v - base_offset
        line = DB.Line.CreateBound(point_at(horizontal[0][0], line_v),
                                   point_at(horizontal[-1][0], line_v))
        plans.append(("Door/window horizontal opening sizes", horizontal, line))
    vertical = unique_chain(vertical_points +
                            [(wall_bottom_ref[0], wall_bottom_ref[1]),
                             (wall_top_ref[0], wall_top_ref[1])])
    if len(vertical) >= 2:
        line_u = max_u + base_offset
        line = DB.Line.CreateBound(point_at(line_u, vertical[0][0]),
                                   point_at(line_u, vertical[-1][0]))
        plans.append(("Door/window vertical opening sizes", vertical, line))
    return plans


def mep_dimension_plans(elements, loops, bounds, point_at, base_offset, chain_step,
                        left_ref, right_ref, view, right, up):
    min_u, max_u, min_v, max_v = bounds
    plans = []
    loop_tolerance = 0.10
    opening_index = 0
    for element in elements:
        box = projected_box(element, view, right, up)
        if not box:
            continue
        candidate = None
        for loop in loops:
            if max(abs(loop["bounds"][index] - box[index]) for index in range(4)) <= loop_tolerance:
                candidate = loop
                break
        if not candidate:
            continue
        opening_bounds = candidate["bounds"]
        if opening_bounds[0] - min_u <= max_u - opening_bounds[1]:
            points = [(left_ref[0], left_ref[1]),
                      (opening_bounds[0], candidate["left"]),
                      (opening_bounds[1], candidate["right"])]
        else:
            points = [(opening_bounds[0], candidate["left"]),
                      (opening_bounds[1], candidate["right"]),
                      (right_ref[0], right_ref[1])]
        points = unique_chain(points)
        if len(points) < 3:
            continue
        line_v = opening_bounds[2] - base_offset - opening_index * chain_step
        line = DB.Line.CreateBound(point_at(points[0][0], line_v),
                                   point_at(points[-1][0], line_v))
        plans.append(("MEP nearest wall end and opening width", points, line))
        opening_index += 1
    return plans


def tube_dimension_plans(elements, bounds, point_at, base_offset, chain_step,
                         right, up, wall_left_ref, wall_right_ref):
    min_u, max_u, min_v, max_v = bounds
    tube_points = []
    for element in elements:
        try:
            family_name = element.Symbol.Family.Name.lower()
            if "tube" not in family_name or "loop" in family_name:
                continue
            location = element.Location
            if not location or location.GetType().Name != "LocationPoint":
                continue
            point = location.Point
            u = point.DotProduct(right)
            v = point.DotProduct(up)
            box = projected_box(element, revit.active_view, right, up)
            if not box or not (min_u - 0.25 <= u <= max_u + 0.25 and min_v - 0.25 <= v <= max_v + 0.25):
                continue
            transform = element.GetTransform()
            refs = list(element.GetReferences(DB.FamilyInstanceReferenceType.CenterLeftRight))
            if refs and abs(transform.BasisX.Normalize().DotProduct(right)) > 0.95:
                tube_points.append((u, refs[0]))
        except Exception:
            continue
    if not tube_points:
        return []
    points = unique_chain(tube_points +
                          [(wall_left_ref[0], wall_left_ref[1]),
                           (wall_right_ref[0], wall_right_ref[1])])
    if len(points) < 2:
        return []
    line_v = min_v - base_offset - chain_step
    line = DB.Line.CreateBound(point_at(points[0][0], line_v),
                               point_at(points[-1][0], line_v))
    return [("Structural grout tube centers", points, line)]


def wall_profile_dimension_plans(walls, door_windows, mep_openings, bounds, point_at,
                                 base_offset, chain_step, right, up, view,
                                 wall_left_ref, wall_right_ref, wall_bottom_ref, wall_top_ref):
    min_u, max_u, min_v, max_v = bounds
    view_direction = view.ViewDirection.Normalize()
    view_depth = view.Origin.DotProduct(view_direction)
    vertical_edges = {}
    horizontal_edges = {}

    def inside_box(u, v, box, tolerance):
        return box and box[0] - tolerance <= u <= box[1] + tolerance and box[2] - tolerance <= v <= box[3] + tolerance

    def touches_bounds(box):
        return (abs(box[0] - min_u) < 0.05 or abs(box[1] - max_u) < 0.05 or
                abs(box[2] - min_v) < 0.05 or abs(box[3] - max_v) < 0.05)

    options = DB.Options()
    options.ComputeReferences = True
    options.View = view

    for wall in walls:
        for obj in wall.get_Geometry(options):
            geometry = obj.GetInstanceGeometry() if isinstance(obj, DB.GeometryInstance) else [obj]
            for solid in geometry:
                if not isinstance(solid, DB.Solid):
                    continue
                for edge in solid.Edges:
                    curve = edge.AsCurve()
                    if not isinstance(curve, DB.Line) or not edge.Reference:
                        continue
                    a = curve.GetEndPoint(0)
                    b = curve.GetEndPoint(1)
                    ua, ub = a.DotProduct(right), b.DotProduct(right)
                    va, vb = a.DotProduct(up), b.DotProduct(up)
                    du, dv = abs(ub - ua), abs(vb - va)
                    if du < 0.015 and dv > 0.10:
                        coordinate = (ua + ub) * 0.5
                        mid_u, mid_v = coordinate, (va + vb) * 0.5
                        store = vertical_edges
                    elif dv < 0.015 and du > 0.10:
                        coordinate = (va + vb) * 0.5
                        mid_u, mid_v = (ua + ub) * 0.5, coordinate
                        store = horizontal_edges
                    else:
                        continue

                    boundary_endpoint = (
                        any(abs(u - boundary) < 0.25 for u in (ua, ub) for boundary in (min_u, max_u)) or
                        any(abs(v - boundary) < 0.25 for v in (va, vb) for boundary in (min_v, max_v)))
                    if not boundary_endpoint:
                        continue

                    excluded = False
                    for opening in door_windows:
                        opening_box = projected_box(opening, view, right, up)
                        if inside_box(mid_u, mid_v, opening_box, 0.02):
                            excluded = True
                            break
                    if excluded:
                        continue

                    for opening in mep_openings:
                        opening_box = projected_box(opening, view, right, up)
                        if inside_box(mid_u, mid_v, opening_box, 0.02) and not touches_bounds(opening_box):
                            excluded = True
                            break
                    if excluded:
                        continue

                    edge_depth = (a.DotProduct(view_direction) + b.DotProduct(view_direction)) * 0.5
                    key = round(coordinate, 2)
                    candidate = (abs(edge_depth - view_depth), edge.Reference)
                    if key not in store or candidate[0] < store[key][0]:
                        store[key] = candidate

    horizontal_points = [(wall_left_ref[0], wall_left_ref[1])]
    for coordinate, value in vertical_edges.items():
        if min_u + 0.25 < coordinate < max_u - 0.25:
            horizontal_points.append((coordinate, value[1]))
    horizontal_points.append((wall_right_ref[0], wall_right_ref[1]))
    horizontal_points = unique_chain(horizontal_points)

    vertical_points = [(wall_bottom_ref[0], wall_bottom_ref[1])]
    for coordinate, value in horizontal_edges.items():
        if min_v + 0.25 < coordinate < max_v - 0.25:
            vertical_points.append((coordinate, value[1]))
    vertical_points.append((wall_top_ref[0], wall_top_ref[1]))
    vertical_points = unique_chain(vertical_points)

    plans = []
    if len(horizontal_points) >= 3:
        line_v = min_v - base_offset - 3 * chain_step
        line = DB.Line.CreateBound(point_at(horizontal_points[0][0], line_v),
                                   point_at(horizontal_points[-1][0], line_v))
        plans.append(("Wall profile and nib horizontal divisions", horizontal_points, line))
    if len(vertical_points) >= 3:
        line_u = max_u + base_offset + 3 * chain_step
        line = DB.Line.CreateBound(point_at(line_u, vertical_points[0][0]),
                                   point_at(line_u, vertical_points[-1][0]))
        plans.append(("Wall profile and nib vertical divisions", vertical_points, line))
    return plans


def create_dimensions(show_message=True):
    doc = revit.doc
    view = doc.ActiveView
    if view.ViewType not in (DB.ViewType.Elevation, DB.ViewType.Detail, DB.ViewType.Section):
        forms.alert("Open an elevation or assembly detail view, then click this button.", exitscript=True)

    walls = list(DB.FilteredElementCollector(doc, view.Id)
                 .OfCategory(DB.BuiltInCategory.OST_Walls)
                 .WhereElementIsNotElementType())
    if not walls:
        forms.alert("No wall is visible in the active view.", exitscript=True)

    right = view.RightDirection.Normalize()
    up = view.UpDirection.Normalize()
    view_direction = view.ViewDirection.Normalize()
    depth = view.Origin.DotProduct(view_direction)
    min_u, max_u, min_v, max_v = projected_wall_bounds(walls, view, right, up)
    left_ref, right_ref, bottom_ref, top_ref = wall_references(walls, view, right, up)

    def point_at(u, v):
        return right * u + up * v + view_direction * depth

    base_offset = max(0.65, view.Scale * 8.0 / 304.8)
    chain_step = max(0.30, view.Scale * 5.0 / 304.8)
    plans = []
    view_bounds = (min_u, max_u, min_v, max_v)
    loops = aperture_loops(walls, view, right, up)

    all_instances = [element for element in DB.FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType()
                     if element.GetType().Name == "FamilyInstance"]
    door_windows = []
    mep_openings = []
    connections = []
    for element in all_instances:
        try:
            category = element.Category.Name if element.Category else ""
            if category in ("Doors", "Windows"):
                door_windows.append(element)
            elif category == "Generic Models":
                family = element.Symbol.Family.Name.lower()
                if "ncp-void" in family or "void" in family:
                    mep_openings.append(element)
            elif category == "Structural Connections":
                connections.append(element)
        except Exception:
            pass

    plans.extend(door_window_dimension_plans(door_windows, view_bounds, point_at,
                                             base_offset, chain_step, right, up, bottom_ref,
                                             top_ref, left_ref, right_ref))
    plans.extend(tube_dimension_plans(connections, view_bounds, point_at,
                                      base_offset, chain_step, right, up,
                                      left_ref, right_ref))
    plans.extend(mep_dimension_plans(mep_openings, loops, view_bounds, point_at,
                                     base_offset, chain_step, left_ref, right_ref,
                                     view, right, up))
    plans.extend(wall_profile_dimension_plans(walls, door_windows, mep_openings,
                                              view_bounds, point_at, base_offset, chain_step,
                                              right, up, view, left_ref, right_ref,
                                              bottom_ref, top_ref))
    plans.append(("Overall wall end-to-end width",
                  [(left_ref[0], left_ref[1]), (right_ref[0], right_ref[1])],
                  DB.Line.CreateBound(point_at(left_ref[0], min_v - base_offset - 2 * chain_step),
                                      point_at(right_ref[0], min_v - base_offset - 2 * chain_step))))
    plans.append(("Overall wall end-to-end height",
                  [(bottom_ref[0], bottom_ref[1]), (top_ref[0], top_ref[1])],
                  DB.Line.CreateBound(point_at(max_u + base_offset + chain_step, bottom_ref[0]),
                                      point_at(max_u + base_offset + chain_step, top_ref[0]))))


    replace_ids = set(globals().get("_AUTO_DIMENSION_REPLACE_IDS", []))
    existing = existing_reference_sets(doc, view, replace_ids)
    planned = set()
    pending = []
    for name, points, line in plans:
        try:
            signature = frozenset(stable_key(item[1], doc) for item in points)
            if not signature or len(signature) < 2 or signature in planned:
                continue
            if any(signature.issubset(old) for old in existing):
                continue
            if name in ("Door/window horizontal opening sizes", "Door/window vertical opening sizes",
                        "Structural grout tube centers", "Wall profile and nib horizontal divisions",
                        "Wall profile and nib vertical divisions"):
                already_complete, partial_ids = matching_existing_chain(doc, view, points, line)
            else:
                already_complete, partial_ids = False, set()
            if already_complete:
                continue
            planned.add(signature)
            pending.append((name, points, line))
        except Exception:
            continue

    if globals().get("_AUTO_DIMENSION_TEST", False):
        test_only = globals().get("_AUTO_DIMENSION_TEST_ONLY")
        if test_only:
            pending = [item for item in pending if test_only in item[0]]

    if not pending:
        if show_message:
            forms.alert("This elevation already has the automatic end-to-end, opening and connection dimension chains.")
        return {"planned": len(plans), "created": 0}

    partial_dimension_ids = set()
    for name, points, line in pending:
        if name in ("Door/window horizontal opening sizes", "Door/window vertical opening sizes",
                    "Structural grout tube centers", "Wall profile and nib horizontal divisions",
                    "Wall profile and nib vertical divisions"):
            already_complete, partial_ids = matching_existing_chain(doc, view, points, line)
            partial_dimension_ids.update(partial_ids)
    replace_ids.update(partial_dimension_ids)
    with revit.Transaction("Auto Elevation Dimensions"):
        for element_id in replace_ids:
            if doc.GetElement(DB.ElementId(int(element_id))):
                doc.Delete(DB.ElementId(int(element_id)))
        for name, points, line in pending:
            references = DB.ReferenceArray()
            for coordinate, reference in points:
                references.Append(reference)
            doc.Create.NewDimension(view, line, references)

    if show_message:
        forms.alert("Added {} dimension chain(s) to '{}'.\n\nIncludes door/window opening sizes, grout tube centers, wall profile and nib divisions, nearest-wall-end MEP opening sizes, and overall wall width and height.".format(
            len(pending), view.Name))
    return {"planned": len(plans), "created": len(pending),
            "door_window_chains": sum(1 for item in pending if "Door/window" in item[0]),
            "mep_chains": sum(1 for item in pending if "MEP" in item[0]),
            "structural_chains": sum(1 for item in pending if "Structural grout tube" in item[0])}


try:
    result = create_dimensions(not globals().get("_AUTO_DIMENSION_TEST", False))
except Exception as error:
    if globals().get("_AUTO_DIMENSION_TEST", False):
        raise
    forms.alert("Could not create elevation dimensions.\n\n{}".format(error), title="Auto Elevation Dimensions")