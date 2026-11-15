# Built as a subdirectory of the pinned ares checkout (see runner/Dockerfile).
add_executable(n64run n64run.cpp)
target_include_directories(n64run PRIVATE ${CMAKE_SOURCE_DIR} ${CMAKE_SOURCE_DIR}/ares)
target_link_libraries(n64run PRIVATE ares::ares ares::mia ares::hiro ares::nall)
set(CONSOLE TRUE)
ares_configure_executable(n64run)
